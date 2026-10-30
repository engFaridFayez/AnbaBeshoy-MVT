from django import forms

from .models import MenuItem


class MenuItemForm(forms.ModelForm):
    class Meta:
        model = MenuItem

        fields = [
            "name",
            "category",
            "icon",
            "is_active",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "اسم الصنف",
                }
            ),

            "category": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "icon": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                }
            ),

            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }