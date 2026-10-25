"""Run: python manage.py test store.tests_web

Uses the project's real store models/services and a minimal test-only base template.
Does not test notification/branding scripts or real mobile push.
"""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from PIL import Image
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client, TestCase, override_settings
from django.urls import include, path, reverse
from django.utils import timezone

from accounts.portal_views import services_home
from .models import Category, Product, StockBatch, StockMovement, UnitOfMeasure
from .services import issue_stock, receive_stock
from .web_selectors import product_card, products_with_balances, with_display_batches


def dummy(request):
    return HttpResponse("test")

urlpatterns = [
    path("store/", include("store.web_urls")),
    path("", include(([
        path("", services_home, name="home"),
        path("meals/", dummy, name="meals"),
        path("login/", dummy, name="login"),
        path("logout/", dummy, name="logout"),
    ], "accounts"), namespace="accounts")),
]

TEST_TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": False,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ],
        "loaders": [
            ("django.template.loaders.locmem.Loader", {
                "accounts/base.html": (
                    '<!doctype html><html lang="ar" dir="rtl"><head>'
                    '<title>{% block title %}{% endblock %}</title>'
                    '{% block extra_css %}{% endblock %}</head><body>'
                    '{% block content %}{% endblock %}'
                    '{% block extra_js %}{% endblock %}</body></html>'
                )
            }),
            "django.template.loaders.app_directories.Loader",
        ],
    },
}]


@override_settings(ROOT_URLCONF=__name__, LOGIN_URL="accounts:login", TEMPLATES=TEST_TEMPLATES)
class StoreWebTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.dev = User.objects.create_user(username="store_web_dev", password="test-password", role="superadmin")
        cls.monk = User.objects.create_user(username="store_web_monk", password="test-password", role="monk")
        cls.admin = User.objects.create_user(username="store_web_admin", password="test-password", role="admin")
        cls.cat = Category.objects.create(name="Test groceries")
        cls.unit = UnitOfMeasure.objects.create(name="Test bottle", symbol="bt")
        cls.product = Product.objects.create(name="Test oil", category=cls.cat, unit=cls.unit,
                                             minimum_stock=10, barcode="001234", requires_expiry_date=True)
        cls.batch = receive_stock(product_id=cls.product.pk, quantity="20", user=cls.dev,
                                  expiry_date=timezone.localdate()+timedelta(days=90))

    def login(self, user=None):
        self.client.force_login(user or self.dev)

    def test_anonymous_catalog_redirects(self):
        self.assertEqual(self.client.get(reverse("store:catalog")).status_code, 302)

    def test_portal_has_both_choices(self):
        self.login(self.monk)
        response = self.client.get(reverse("accounts:home"))
        self.assertContains(response, reverse("accounts:meals"))
        self.assertContains(response, reverse("store:catalog"))

    def test_monk_can_browse(self):
        self.login(self.monk)
        self.assertContains(self.client.get(reverse("store:catalog")), "Test oil")

    def test_developer_can_browse(self):
        self.login()
        self.assertContains(self.client.get(reverse("store:catalog")), reverse("store:product_add"))

    def test_monk_cannot_view_history(self):
        self.login(self.monk)
        self.assertEqual(self.client.get(reverse("store:movements", args=[self.product.pk])).status_code, 403)

    def test_monk_detail_has_no_batch_rows(self):
        self.login(self.monk)
        response = self.client.get(reverse("store:product", args=[self.product.pk]))
        self.assertNotIn("batch_rows", response.context)

    def test_monk_cannot_receive(self):
        self.login(self.monk)
        self.assertEqual(self.client.post(reverse("store:receive", args=[self.product.pk]), {}).status_code, 403)

    def test_admin_role_alone_cannot_issue(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("store:issue", args=[self.product.pk])).status_code, 403)

    def test_admin_with_stock_permission_can_issue(self):
        perm = Permission.objects.get(content_type__app_label="store", codename="add_stockmovement")
        self.admin.user_permissions.add(perm)
        self.login(self.admin)
        response = self.client.post(reverse("store:issue", args=[self.product.pk]), {"quantity":"7", "recipient":"Kitchen"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.available_stock, Decimal("13"))

    def test_receive_records_one_batch(self):
        self.login()
        before = StockBatch.objects.count()
        response = self.client.post(reverse("store:receive", args=[self.product.pk]), {
            "quantity":"5", "received_date":timezone.localdate().isoformat(),
            "expiry_date":(timezone.localdate()+timedelta(days=30)).isoformat(), "source":"purchase",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StockBatch.objects.count(), before+1)
        self.assertEqual(self.product.available_stock, Decimal("25"))

    def test_insufficient_stock_no_write(self):
        self.login()
        before = StockMovement.objects.count()
        response = self.client.post(reverse("store:issue", args=[self.product.pk]), {"quantity":"21", "recipient":"Kitchen"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(StockMovement.objects.count(), before)

    def test_fraction_rejected_for_bottles(self):
        self.login()
        response = self.client.post(reverse("store:issue", args=[self.product.pk]), {"quantity":"1.5", "recipient":"Kitchen"})
        self.assertIn("quantity", response.context["form"].errors)

    def test_negative_rejected(self):
        self.login()
        response = self.client.post(reverse("store:issue", args=[self.product.pk]), {"quantity":"-1", "recipient":"Kitchen"})
        self.assertIn("quantity", response.context["form"].errors)

    def test_bad_date_shows_form_errors(self):
        self.login()
        response = self.client.post(reverse("store:receive", args=[self.product.pk]), {
            "quantity":"2", "received_date":"nonsense", "source":"purchase",
            "expiry_date":(timezone.localdate()+timedelta(days=30)).isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("received_date", response.context["form"].errors)

    def test_future_receipt_rejected_by_service(self):
        self.login()
        response = self.client.post(reverse("store:receive", args=[self.product.pk]), {
            "quantity":"2", "source":"purchase",
            "received_date":(timezone.localdate()+timedelta(days=5)).isoformat(),
            "expiry_date":(timezone.localdate()+timedelta(days=30)).isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_get_operation_does_not_write(self):
        self.login()
        before = StockMovement.objects.count()
        self.client.get(reverse("store:receive", args=[self.product.pk]))
        self.client.get(reverse("store:issue", args=[self.product.pk]))
        self.assertEqual(StockMovement.objects.count(), before)

    def test_low_border_after_reaching_threshold(self):
        issue_stock(product_id=self.product.pk, quantity="10", user=self.dev, recipient="Kitchen")
        self.login()
        response = self.client.get(reverse("store:catalog"), {"state":"low"})
        self.assertContains(response, 'data-low="true"')
        self.assertContains(response, "Test oil")

    def test_barcode_keeps_leading_zero(self):
        self.login(self.monk)
        self.assertContains(self.client.get(reverse("store:catalog"), {"q":"001234"}), "Test oil")

    def test_invalid_filters_do_not_crash(self):
        self.login()
        response = self.client.get(reverse("store:catalog"), {"category":"bad", "state":"invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_inactive_hidden_from_monk(self):
        self.product.is_active=False
        self.product.save()
        self.login(self.monk)
        response = self.client.get(reverse("store:catalog"), {"include_inactive":"on"})
        self.assertNotContains(response, "Test oil")
        self.assertEqual(self.client.get(reverse("store:product", args=[self.product.pk])).status_code, 404)

    def test_inactive_visible_to_manager_on_request(self):
        self.product.is_active=False
        self.product.save()
        self.login()
        self.assertContains(self.client.get(reverse("store:catalog"), {"include_inactive":"on"}), "Test oil")

    def test_expired_stock_is_not_available(self):
        self.batch.expiry_date=timezone.localdate()-timedelta(days=1)
        self.batch.save()
        product = with_display_batches(products_with_balances()).get(pk=self.product.pk)
        card = product_card(product)
        self.assertEqual(card["available"], "0")
        self.assertEqual(card["total"], "20")
        self.assertEqual(card["expired_count"], 1)

    def test_expiring_filter_uses_product_threshold(self):
        self.batch.expiry_date=timezone.localdate()+timedelta(days=3)
        self.batch.save()
        self.login()
        self.assertContains(self.client.get(reverse("store:catalog"), {"state":"expiring"}), "Test oil")

    def test_empty_batch_does_not_warn_expiry(self):
        issue_stock(product_id=self.product.pk, quantity="20", user=self.dev, recipient="Kitchen")
        self.batch.expiry_date=timezone.localdate()+timedelta(days=2)
        self.batch.save()
        self.login()
        self.assertNotContains(self.client.get(reverse("store:catalog"), {"state":"expiring"}), "Test oil")

    def test_monk_cannot_add_product(self):
        self.login(self.monk)
        self.assertEqual(self.client.get(reverse("store:product_add")).status_code, 403)

    def test_developer_adds_product_no_stock(self):
        self.login()
        response = self.client.post(reverse("store:product_add"), {
            "name":"New item", "category":self.cat.pk, "unit":self.unit.pk,
            "minimum_stock":"0", "expiry_warning_days":"7", "is_active":"on",
        })
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name="New item")
        self.assertEqual(product.current_stock, Decimal("0"))

    def test_product_unit_disabled_after_receipt(self):
        self.login()
        response = self.client.get(reverse("store:product_edit", args=[self.product.pk]))
        self.assertTrue(response.context["form"].fields["unit"].disabled)

    def test_product_with_history_cannot_be_deleted(self):
        self.login()
        response = self.client.post(reverse("store:delete", args=["products",self.product.pk]), {"confirm":"yes"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_delete_requires_confirmation(self):
        empty = Category.objects.create(name="Empty category")
        self.login()
        self.client.post(reverse("store:delete", args=["categories",empty.pk]), {})
        self.assertTrue(Category.objects.filter(pk=empty.pk).exists())

    def test_empty_category_can_be_deleted(self):
        empty = Category.objects.create(name="Empty category")
        self.login()
        response = self.client.post(reverse("store:delete", args=["categories",empty.pk]), {"confirm":"yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Category.objects.filter(pk=empty.pk).exists())

    def test_category_with_products_protected(self):
        self.login()
        response = self.client.post(reverse("store:delete", args=["categories",self.cat.pk]), {"confirm":"yes"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Category.objects.filter(pk=self.cat.pk).exists())

    def test_get_delete_never_deletes(self):
        self.login()
        self.client.get(reverse("store:delete", args=["categories",self.cat.pk]))
        self.assertTrue(Category.objects.filter(pk=self.cat.pk).exists())

    def test_csrf_required_for_write(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.dev)
        response = client.post(reverse("store:issue", args=[self.product.pk]), {"quantity":"1", "recipient":"Kitchen"})
        self.assertEqual(response.status_code, 403)

    def test_history_page_renders(self):
        self.login()
        self.assertEqual(self.client.get(reverse("store:movements", args=[self.product.pk])).status_code, 200)

    def test_grant_command_rejects_monk(self):
        with self.assertRaises(CommandError):
            call_command("grant_store_access", username=self.monk.username)

    def test_grant_command_does_not_enable_staff(self):
        call_command("grant_store_access", username=self.admin.username)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_staff)
        self.assertFalse(self.admin.is_superuser)
        self.assertEqual(self.admin.role, "admin")
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("store:issue", args=[self.product.pk])).status_code, 200)

    def test_non_image_upload_rejected(self):
        self.login()
        response = self.client.post(reverse("store:product_add"), {
            "name":"Bad image item", "category":self.cat.pk, "unit":self.unit.pk,
            "minimum_stock":"0", "expiry_warning_days":"7", "is_active":"on",
            "image":SimpleUploadedFile("photo.png", b"not an image", content_type="image/png"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("image", response.context["form"].errors)

    def test_image_upload_and_template_url(self):
        self.login()
        output = BytesIO()
        Image.new("RGB", (8, 8), "white").save(output, "PNG")
        with TemporaryDirectory() as media:
            with self.settings(MEDIA_ROOT=media, MEDIA_URL="/media/"):
                response = self.client.post(reverse("store:product_add"), {
                    "name":"Image item", "category":self.cat.pk, "unit":self.unit.pk,
                    "minimum_stock":"0", "expiry_warning_days":"7", "is_active":"on",
                    "image":SimpleUploadedFile("photo.png", output.getvalue(), content_type="image/png"),
                })
                self.assertEqual(response.status_code, 302)
                item = Product.objects.get(name="Image item")
                self.assertContains(self.client.get(reverse("store:product", args=[item.pk])), item.image.url)
