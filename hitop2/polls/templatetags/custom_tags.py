from django import template

from polls.translations import translate_spectrum as get_spectrum_translation

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def translate_spectrum(name):
    return get_spectrum_translation(name)
