# hitop2/polls/templatetags/custom_tags.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Retorna o valor de um dicionário para a chave fornecida"""
    return dictionary.get(key)