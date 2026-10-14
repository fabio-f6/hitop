from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from polls.models import QuestionnaireCollection
from website.decorators import can_use_general_collections

from .models import EmailNotification
from .services import absolute_url, queue_notification


def collection_digest_period(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), datetime.min.time()), tz)
    return start, end


def queue_collection_digests(day):
    start, end = collection_digest_period(day)
    collections = (
        QuestionnaireCollection.objects.filter(
            is_test_data=False,
            submissions__completed=True,
            submissions__completed_at__gte=start,
            submissions__completed_at__lt=end,
        )
        .select_related("owner", "owner__userprofile")
        .annotate(
            new_count=Count(
                "submissions",
                filter=Q(
                    submissions__completed=True,
                    submissions__completed_at__gte=start,
                    submissions__completed_at__lt=end,
                    submissions__is_test_data=False,
                    submissions__simulation_mode="normal",
                ),
                distinct=True,
            ),
            total_count=Count(
                "submissions",
                filter=Q(
                    submissions__completed=True,
                    submissions__is_test_data=False,
                    submissions__simulation_mode="normal",
                ),
                distinct=True,
            ),
        )
        .filter(new_count__gt=0)
        .order_by("owner_id", "name")
    )
    grouped = {}
    for collection in collections:
        if not can_use_general_collections(collection.owner):
            continue
        grouped.setdefault(collection.owner, []).append({
            "name": collection.name,
            "new_count": collection.new_count,
            "total_count": collection.total_count,
        })
    queued = []
    with transaction.atomic():
        for owner, rows in grouped.items():
            notification, created = queue_notification(
                notification_type=EmailNotification.Type.COLLECTION_DAILY_SUMMARY,
                logical_key=f"collection-digest:{day.isoformat()}:owner:{owner.pk}",
                recipient=owner,
                context={
                    "digest_date": day.isoformat(),
                    "collections": rows,
                    "action_url": absolute_url("website:collection_list"),
                },
            )
            if created:
                queued.append(notification)
    return queued
