from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django import forms
from .models import UserProfile, Record

class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        label="",
        widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'Email Address'})
    )
    first_name = forms.CharField(
        label="", max_length=100,
        widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'First Name'})
    )
    last_name = forms.CharField(
        label="", max_length=100,
        widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'Last Name'})
    )

    user_type = forms.ChoiceField(
        label="",
        choices=[('', 'User Type')] + list(UserProfile.USER_TYPES),
        widget=forms.Select(attrs={'class':'form-control'})
    )

    professional = forms.ModelChoiceField(
        label="",
        queryset=User.objects.filter(userprofile__user_type='professional'),
        required=False,
        widget=forms.Select(attrs={'class':'form-control'})
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2', 'user_type', 'professional')

    def __init__(self, *args, **kwargs):
        super(SignUpForm, self).__init__(*args, **kwargs)

        # Estilizando os campos já existentes
        self.fields['username'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Username'})
        self.fields['username'].label = ''
        self.fields['username'].help_text = '<span class="form-text text-muted"><small>Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.</small></span>'

        self.fields['password1'].widget.attrs.update({'class':'form-control', 'placeholder':'Password'})
        self.fields['password1'].label = ''
        self.fields['password1'].help_text = (
            '<ul class="form-text text-muted small">'
            '<li>Your password can\'t be too similar to your other personal information.</li>'
            '<li>Your password must contain at least 8 characters.</li>'
            '<li>Your password can\'t be a commonly used password.</li>'
            '<li>Your password can\'t be entirely numeric.</li>'
            '</ul>'
        )

        self.fields['password2'].widget.attrs.update({'class':'form-control', 'placeholder':'Confirm Password'})
        self.fields['password2'].label = ''
        self.fields['password2'].help_text = '<span class="form-text text-muted"><small>Enter the same password as before, for verification.</small></span>'

        self.fields['user_type'].widget.attrs.update({'class': 'form-control'})
        self.fields['professional'].widget.attrs.update({'class': 'form-control'})

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