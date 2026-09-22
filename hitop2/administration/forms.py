from django import forms


class NormativeVersionCreateForm(forms.Form):
    name = forms.CharField(
        label="Nome da versão",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": "form-control rounded-0",
                "placeholder": "Ex.: v2",
                "autocomplete": "off",
            }
        ),
    )

