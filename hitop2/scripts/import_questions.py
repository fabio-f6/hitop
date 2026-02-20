import os
import sys
import django

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hitop2.settings")
django.setup()

from polls.models import Scale, Subscale, Question

scales_list = [
    "Dishonesty",
    "Distress-Dysphoria",
]

scales = {}
for name in scales_list:
    scale_obj, created = Scale.objects.get_or_create(name=name)
    scales[name] = scale_obj

subscales_list = [
    {"name": "Deceitfulness", "scale": "Dishonesty"},
    {"name": "Manipulativeness", "scale": "Dishonesty"},
    {"name": "Anhedonia", "scale": "Distress-Dysphoria"},
    {"name": "Anxious Worry", "scale": "Distress-Dysphoria"},
    {"name": "Depressed Mood", "scale": "Distress-Dysphoria"},
    {"name": "Lassitude", "scale": "Distress-Dysphoria"},
    {"name": "Shame/Guilt", "scale": "Distress-Dysphoria"},
]

subscales = {}
for s in subscales_list:
    scale_obj = scales[s["scale"]]
    sub_obj, created = Subscale.objects.get_or_create(name=s["name"], scale=scale_obj)
    subscales[s["name"]] = sub_obj

questions_data = [
    {"scale": "Dishonesty", "subscale": "Deceitfulness", "item_code": "Ext_303", "rk": False, "question_text": "I said things that were not true."},
    {"scale": "Dishonesty", "subscale": "Deceitfulness", "item_code": "Ext_395", "rk": False, "question_text": "I was willing to tell a small lie to make things easier for myself."},
    {"scale": "Dishonesty", "subscale": "Deceitfulness", "item_code": "Ext_432", "rk": False, "question_text": "I believed it was fine to tell a little lie in order to get out of trouble."},
    {"scale": "Dishonesty", "subscale": "Deceitfulness", "item_code": "Ext_444", "rk": False, "question_text": "I lied about myself to other people."},
    {"scale": "Dishonesty", "subscale": "Manipulativeness", "item_code": "Ext_101", "rk": False, "question_text": "I tried to con or cheat other people."},
    {"scale": "Dishonesty", "subscale": "Manipulativeness", "item_code": "Ext_22", "rk": False, "question_text": "I found it easy to deceive others."},
    {"scale": "Dishonesty", "subscale": "Manipulativeness", "item_code": "Ext_262", "rk": False, "question_text": "I found it easy to manipulate others."},
    {"scale": "Dishonesty", "subscale": "Manipulativeness", "item_code": "Ext_38", "rk": False, "question_text": "I made people believe almost anything."},
    {"scale": "Distress-Dysphoria", "subscale": "Anhedonia", "item_code": "HiTOP_173", "rk": False, "question_text": "Nothing seemed interesting to me."},
    {"scale": "Distress-Dysphoria", "subscale": "Anhedonia", "item_code": "HiTOP_508", "rk": False, "question_text": "I didn't get excited about very much."},
    {"scale": "Distress-Dysphoria", "subscale": "Anhedonia", "item_code": "HiTOP_8", "rk": False, "question_text": "I didn't experience the joy and pleasure that most other people do."},
    {"scale": "Distress-Dysphoria", "subscale": "Anxious Worry", "item_code": "HiTOP_187", "rk": False, "question_text": "I was overwhelmed by anxiety."},
    {"scale": "Distress-Dysphoria", "subscale": "Anxious Worry", "item_code": "HiTOP_190", "rk": False, "question_text": "I felt nervous and on edge."},
    {"scale": "Distress-Dysphoria", "subscale": "Anxious Worry", "item_code": "HiTOP_191", "rk": False, "question_text": "I felt very stressed."},
    {"scale": "Distress-Dysphoria", "subscale": "Depressed Mood", "item_code": "exp12", "rk": False, "question_text": "I felt hopeless about the future."},
    {"scale": "Distress-Dysphoria", "subscale": "Depressed Mood", "item_code": "exp14", "rk": False, "question_text": "I felt worthless."},
    {"scale": "Distress-Dysphoria", "subscale": "Depressed Mood", "item_code": "exp8", "rk": False, "question_text": "I felt depressed."},
    {"scale": "Distress-Dysphoria", "subscale": "Depressed Mood", "item_code": "exp9", "rk": False, "question_text": "I felt down and discouraged."},
    {"scale": "Distress-Dysphoria", "subscale": "Lassitude", "item_code": "exp17", "rk": False, "question_text": "Took a lot of effort to get going."},
    {"scale": "Distress-Dysphoria", "subscale": "Lassitude", "item_code": "exp18", "rk": False, "question_text": "I had very little energy."},
    {"scale": "Distress-Dysphoria", "subscale": "Lassitude", "item_code": "exp19", "rk": False, "question_text": "I felt worn out."},
    {"scale": "Distress-Dysphoria", "subscale": "Shame/Guilt", "item_code": "HiTOP_333", "rk": False, "question_text": "I was disgusted with myself."},
    {"scale": "Distress-Dysphoria", "subscale": "Shame/Guilt", "item_code": "HiTOP_334", "rk": False, "question_text": "I blamed myself for things."},
    {"scale": "Distress-Dysphoria", "subscale": "Shame/Guilt", "item_code": "HiTOP_336", "rk": False, "question_text": "I was ashamed of myself."},
]

for q in questions_data:
    scale_obj = scales[q["scale"]]
    sub_obj = subscales[q["subscale"]]
    Question.objects.create(
        scale=scale_obj,
        subscale=sub_obj,
        item_code=q["item_code"],
        rk=q["rk"],
        question_text=q["question_text"]
    )

print(f"{len(questions_data)} perguntas criadas com sucesso!")