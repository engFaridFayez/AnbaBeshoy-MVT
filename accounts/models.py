from django.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.

class User(AbstractUser):

    class Role(models.TextChoices):
        MONK = "monk", "راهب",
        ADMIN = "admin", "راهب مسؤول",
        SUPERADMIN = "superadmin", "superadmin",

    display_name = models.CharField(max_length=255, blank=True, null=True)

    code = models.CharField(max_length=255, blank=True, null=True)

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MONK,
    )

    def __str__(self):
        return self.display_name or self.username
