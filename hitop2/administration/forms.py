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


class MasterResetConfirmationForm(forms.Form):
    confirmation = forms.CharField(
        label="Frase de confirmação",
        strip=False,
        widget=forms.TextInput(attrs={
            "class": "form-control rounded-0",
            "autocomplete": "off",
            "placeholder": "MASTER RESET",
        }),
    )
    password = forms.CharField(
        label="Password atual",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "form-control rounded-0",
            "autocomplete": "current-password",
        }),
    )

    def clean_confirmation(self):
        confirmation = self.cleaned_data["confirmation"]
        if confirmation != "MASTER RESET":
            raise forms.ValidationError("A frase de confirmação não corresponde.")
        return confirmation
