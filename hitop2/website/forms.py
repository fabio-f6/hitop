from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django import forms
from .models import UserProfile
from polls.models import Spectra, QuestionnaireSubmission
from polls.questions import get_scientific_spectra
import random
import string


class SimulationConfigurationMixin:
    simulation_field_names = (
        "simulation_mode",
        "sociodemographic_simulation_mode",
        "simulation_response_profile",
        "simulation_missing_percentage",
        "simulation_attention_mode",
        "simulation_seed",
    )

    simulation_defaults = {
        "simulation_mode": "normal",
        "sociodemographic_simulation_mode": "normal",
        "simulation_response_profile": "random",
        "simulation_missing_percentage": 0,
        "simulation_attention_mode": "all_correct",
        "simulation_seed": None,
    }

    def configure_simulation_fields(self, *, allow_simulation):
        self.allow_simulation = allow_simulation
        if allow_simulation:
            self.add_simulation_fields()

    def add_simulation_fields(self):
        self.fields["simulation_mode"] = forms.TypedChoiceField(
            label="Modo da aplicação:",
            choices=QuestionnaireSubmission.SIMULATION_MODES,
            initial="normal",
            widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
            coerce=str,
        )
        self.fields["sociodemographic_simulation_mode"] = forms.ChoiceField(
            label="Sociodemográfico",
            choices=(
                QuestionnaireSubmission.SociodemographicSimulationMode.choices
            ),
            initial=QuestionnaireSubmission.SociodemographicSimulationMode.NORMAL,
            required=False,
            widget=forms.Select(attrs={"class": "form-select"}),
        )
        self.fields["simulation_response_profile"] = forms.ChoiceField(
            label="Perfil de respostas",
            choices=QuestionnaireSubmission.SimulationResponseProfile.choices,
            initial=QuestionnaireSubmission.SimulationResponseProfile.RANDOM,
            required=False,
            widget=forms.Select(attrs={"class": "form-select"}),
        )
        self.fields["simulation_missing_percentage"] = forms.TypedChoiceField(
            label="Omissões",
            choices=QuestionnaireSubmission.SIMULATION_MISSING_PERCENTAGES,
            initial=0,
            coerce=int,
            empty_value=0,
            required=False,
            widget=forms.Select(attrs={"class": "form-select"}),
        )
        self.fields["simulation_attention_mode"] = forms.ChoiceField(
            label="Attention checks",
            choices=QuestionnaireSubmission.SimulationAttentionMode.choices,
            initial=QuestionnaireSubmission.SimulationAttentionMode.ALL_CORRECT,
            required=False,
            widget=forms.Select(attrs={"class": "form-select"}),
        )
        self.fields["simulation_seed"] = forms.IntegerField(
            label="Seed",
            required=False,
            widget=forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Opcional",
            }),
        )

    def clean(self):
        cleaned_data = super().clean()
        if not self.allow_simulation:
            cleaned_data.update(self.simulation_defaults)
            return cleaned_data

        mode = cleaned_data.get("simulation_mode", "normal")
        cleaned_data["sociodemographic_simulation_mode"] = (
            cleaned_data.get("sociodemographic_simulation_mode") or "normal"
        )
        cleaned_data["simulation_response_profile"] = (
            cleaned_data.get("simulation_response_profile") or "random"
        )
        cleaned_data["simulation_attention_mode"] = (
            cleaned_data.get("simulation_attention_mode") or "all_correct"
        )
        cleaned_data["simulation_missing_percentage"] = (
            cleaned_data.get("simulation_missing_percentage") or 0
        )
        if mode == "normal":
            cleaned_data.update({
                "sociodemographic_simulation_mode": "normal",
                "simulation_response_profile": "random",
                "simulation_missing_percentage": 0,
                "simulation_attention_mode": "all_correct",
                "simulation_seed": None,
            })
        elif (
            mode == "simulated_nulls"
            and not cleaned_data.get("simulation_missing_percentage")
        ):
            cleaned_data["simulation_missing_percentage"] = 10
        return cleaned_data

    def simulation_configuration(self):
        if not self.allow_simulation:
            return self.simulation_defaults.copy()
        return {name: self.cleaned_data[name] for name in self.simulation_field_names}

class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        label="", widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'Email'})
    )
    first_name = forms.CharField(
        label="", max_length=100, widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'Nome'})
    )
    last_name = forms.CharField(
        label="", max_length=100, widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'Apelido'})
    )

    # Novos campos do UserProfile
    area_formacao = forms.ChoiceField(
        label="Área de formação do requerente",
        choices=UserProfile._meta.get_field('area_formacao').choices,
        widget=forms.Select(attrs={'class':'form-control'})
    )

    objetivo_uso = forms.ChoiceField(
        label="Objetivo do uso do instrumento",
        choices=UserProfile._meta.get_field('objetivo_uso').choices,
        widget=forms.Select(attrs={'class':'form-control'})
    )

    cedula_profissional = forms.CharField(
        label="Cédula profissional",
        widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'Número da cédula profissional'})
    )

    class Meta:
        model = User
        fields = (
            'first_name', 
            'last_name', 
            'email',
            'password1', 
            'password2',
            'area_formacao', 
            'objetivo_uso', 
            'cedula_profissional', 
            'username',  # escondido
        )

    def __init__(self, *args, **kwargs):
        super(SignUpForm, self).__init__(*args, **kwargs)

        # Oculta o username
        self.fields['username'].widget = forms.HiddenInput()
        self.fields['username'].required = False

        # Password1
        self.fields['password1'].widget.attrs.update({'class':'form-control', 'placeholder':'Palavra-passe'})
        self.fields['password1'].label = ''
        self.fields['password1'].help_text = (
            '<ul class="form-text text-muted small">'
            '<li>A sua palavra-passe não pode ser demasiado semelhante a outras informações pessoais.</li>'
            '<li>A sua palavra-passe deve conter pelo menos 8 caracteres.</li>'
            '<li>A sua palavra-passe não pode ser uma palavra-passe comum.</li>'
            '<li>A sua palavra-passe não pode ser inteiramente numérica.</li>'
            '</ul>'
        )

        # Password2
        self.fields['password2'].widget.attrs.update({'class':'form-control', 'placeholder':'Confirmar palavra-passe'})
        self.fields['password2'].label = ''
        self.fields['password2'].help_text = (
            '<span class="form-text text-muted"><small>Insira a mesma palavra-passe novamente para verificação.</small></span>'
        )

class CreatePatientForm(SimulationConfigurationMixin, UserCreationForm):

    username = forms.CharField(
        label="ID de Utilizador",
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "readonly": True,
            "style": "background-color: #f5f5f5;",
        })
    )

    password1 = forms.CharField(
        label="Palavra-passe",
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "readonly": True,
            "style": "background-color: #f5f5f5;",
        })
    )

    password2 = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    title = forms.CharField(
        label="Descrição da aplicação",
        max_length=255,
        required=True,
        initial="Avaliação Inicial",
        widget=forms.TextInput(attrs={
            "class": "form-control"
        })
    )

    spectra = forms.ModelMultipleChoiceField(
        queryset=get_scientific_spectra(),
        widget=forms.CheckboxSelectMultiple(attrs={
            "class": "form-check-input",
        }),
        required=True,
    )

    class Meta:
        model = User
        fields = (
            "username",
            "password1",
            "password2",
        )

    def __init__(self, *args, allow_simulation=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.configure_simulation_fields(allow_simulation=allow_simulation)

        def generate_username():
            return "P_" + "".join(
                random.choices(
                    string.ascii_lowercase + string.digits,
                    k=6
                )
            )

        def generate_password():
            return "PW_" + "".join(
                random.choices(
                    string.ascii_letters + string.digits,
                    k=6
                )
            )

        username = generate_username()

        while User.objects.filter(
            username=username
        ).exists():
            username = generate_username()

        self.generated_username = username
        self.fields["username"].initial = username

        password = generate_password()
        self.generated_password = password

        self.fields["password1"].initial = password
        self.fields["password2"].initial = password

    def clean(self):
        cleaned_data = super().clean()

        cleaned_data["password1"] = self.generated_password
        cleaned_data["password2"] = self.generated_password

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)

        user.username = self.generated_username
        user.set_password(self.generated_password)

        if commit:
            user.save()

        return user


class NewQuestionnaireForm(SimulationConfigurationMixin, forms.Form):
    title = forms.CharField(
        label="Descrição da aplicação",
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ex: Avaliação após 3 meses de terapia",
        }),
    )
    spectra = forms.ModelMultipleChoiceField(
        label="Módulos a incluir:",
        queryset=get_scientific_spectra(),
        widget=forms.CheckboxSelectMultiple(attrs={
            "class": "form-check-input",
        }),
        required=True,
    )

    def __init__(self, *args, allow_simulation=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.configure_simulation_fields(allow_simulation=allow_simulation)
        if allow_simulation:
            self.order_fields((
                "title",
                *self.simulation_field_names,
                "spectra",
            ))

class EditPatientForm(forms.ModelForm):
    spectra = forms.ModelMultipleChoiceField(
        queryset=get_scientific_spectra(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Módulos (HiTOP)"
        )

    class Meta:
        model = UserProfile
        fields = ['spectra']
