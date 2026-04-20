from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django import forms
from .models import UserProfile, Record
from polls.models import Spectra
import random, string

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

class CreatePatientForm(UserCreationForm):
    username = forms.CharField(
        label="",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': True,
            'style': 'background-color: #f5f5f5;'
        })
    )

    password1 = forms.CharField(
        label="",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Palavra-passe'
        })
    )

    password2 = forms.CharField(
        label="",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirmar palavra-passe'
        })
    )

    spectra = forms.ModelMultipleChoiceField(
        queryset=Spectra.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True
    )

    class Meta:
        model = User
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        def generate_username():
            return 'P_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

        username = generate_username()
        while User.objects.filter(username=username).exists():
            username = generate_username()

        self.generated_username = username
        self.fields['username'].initial = username

    def save(self, commit=True):
        user = super().save(commit=False)

        user.username = self.generated_username

        if commit:
            user.save()

        return user

class EditPatientForm(forms.ModelForm):
    spectra = forms.ModelMultipleChoiceField(
        queryset=Spectra.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Módulos (HiTOP)"
        )

    class Meta:
        model = UserProfile
        fields = ['spectra']

class AddRecordForm(forms.ModelForm):
	first_name = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"First name", "class":"form-control"}), label="")
	last_name = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"Last name", "class":"form-control"}), label="")
	email = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"Email", "class":"form-control"}), label="")
	phone = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"Phone", "class":"form-control"}), label="")
	address = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"Address", "class":"form-control"}), label="")
	city = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"City", "class":"form-control"}), label="")
	state = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"State", "class":"form-control"}), label="")
	zipcode = forms.CharField(required=True, widget=forms.widgets.TextInput(attrs={"placeholder":"Zipcode", "class":"form-control"}), label="")

	class Meta:
		model = Record
		exclude = ("user",)