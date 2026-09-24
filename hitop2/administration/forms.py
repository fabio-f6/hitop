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


class NormativeBaselineChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return (
            f"{obj.name} — {obj.get_environment_display()} — "
            f"{obj.participant_count} participantes"
        )


class NormativeTestVersionCreateForm(NormativeVersionCreateForm):
    baseline_version = NormativeBaselineChoiceField(
        label="Versão de base (produção ou teste)",
        queryset=None,
        widget=forms.Select(attrs={"class": "form-select rounded-0"}),
    )

    def __init__(self, *args, **kwargs):
        from polls.models import NormativeDatasetVersion
        super().__init__(*args, **kwargs)
        self.fields["baseline_version"].queryset = NormativeDatasetVersion.objects.all().order_by(
            "-created_at", "-id"
        )


class NormativeTestCleanupForm(forms.Form):
    confirmation = forms.CharField(
        label="Confirmação",
        strip=False,
        widget=forms.TextInput(attrs={
            "class": "form-control rounded-0",
            "autocomplete": "off",
            "placeholder": "LIMPAR TESTE NORMATIVO",
        }),
    )

    def clean_confirmation(self):
        value = self.cleaned_data["confirmation"]
        if value != "LIMPAR TESTE NORMATIVO":
            raise forms.ValidationError("A frase de confirmação não corresponde.")
        return value


class ProfessionalTestEnvironmentCleanupForm(forms.Form):
    confirmation = forms.CharField(
        label="Frase de confirmação",
        strip=False,
        widget=forms.TextInput(attrs={
            "class": "form-control rounded-0",
            "autocomplete": "off",
            "placeholder": "APAGAR AMBIENTE PROFISSIONAL DE TESTE",
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
        value = self.cleaned_data["confirmation"]
        if value != "APAGAR AMBIENTE PROFISSIONAL DE TESTE":
            raise forms.ValidationError("A frase de confirmação não corresponde.")
        return value
