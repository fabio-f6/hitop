from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import SignUpForm, AddRecordForm
from .models import Record, UserProfile
from polls.models import UserAnswer

def home(request):
    records = Record.objects.all()

    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "Logged in successfully!")
            return redirect('polls:questionnaire')
        else:
            messages.error(request, "Invalid username or password.")
            return redirect('website:home')
    else:
        return render(request, 'website/home.html', {'records': records})

def logout_user(request):
    logout(request)
    messages.success(request, "Logged out successfully!")
    return redirect('website:home')

def register_user(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            user_type = form.cleaned_data['user_type']
            professional = form.cleaned_data.get('professional')

            profile = user.userprofile
            profile.user_type = user_type
            profile.professional = professional
            profile.save()


            # autentica e loga o usuário
            username = form.cleaned_data['username']
            password = form.cleaned_data['password1']
            user = authenticate(request, username=username, password=password)
            login(request, user)

            messages.success(request, "Registration successful!")
            return redirect('website:home')
    else:
        form = SignUpForm()

    return render(request, 'website/register.html', {'form': form})

def customer_record(request, pk):
    if request.user.is_authenticated:
        customer_record = Record.objects.get(id=pk)
        return render(request, 'website/record.html', {'customer_record': customer_record})
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

def delete_record(request, pk):
    if request.user.is_authenticated:
        delete_it = Record.objects.get(id=pk)
        delete_it.delete()
        messages.success(request, "Record deleted successfully.")
        return redirect('website:home')
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

def add_record(request):
    form = AddRecordForm(request.POST or None)
    if request.user.is_authenticated:
        if request.method == "POST":
            if form.is_valid():
                add_record = form.save()
                messages.success(request, "Record added successfully.")
                return redirect('website:home')
        else:
            return render(request, 'website/add_record.html', {'form':form})
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

def update_record(request, pk):
    if request.user.is_authenticated:
        current_record = Record.objects.get(id=pk)
        form = AddRecordForm(request.POST or None, instance=current_record)
        if form.is_valid():
            form.save()
            messages.success(request, "Record updated successfully.")
            return redirect('record', pk=pk)
        return render(request, 'website/update_record.html', {'form':form, 'record':current_record})
    else:
        messages.error(request, "You must be logged in to view that page.")
        return redirect('website:home')

# website/views.py
@login_required
def my_patients(request):
    # Apenas profissionais podem acessar
    if request.user.userprofile.user_type != 'professional':
        messages.error(request, "Acesso negado.")
        return redirect('website:home')

    patients = request.user.patients.all()  # todos os pacientes associados
    return render(request, 'website/my_patients.html', {'patients': patients})

@login_required
def patient_answers(request, patient_id):
    if request.user.userprofile.user_type != 'professional':
        messages.error(request, "Acesso negado.")
        return redirect('website:home')

    try:
        # já filtra pelo paciente associado ao profissional logado
        patient_profile = UserProfile.objects.get(user__id=patient_id, professional=request.user)
    except UserProfile.DoesNotExist:
        messages.error(request, "Paciente não encontrado ou não associado a você.")
        return redirect('website:my_patients')

    answers = UserAnswer.objects.filter(user=patient_profile.user)
    return render(request, 'website/patient_answers.html', {
        'patient': patient_profile.user,
        'answers': answers
    })