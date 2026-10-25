"""تشغيل: python manage.py test store.tests_stock

اختبارات معزولة باستخدام قاعدة الاختبار التي ينشئها Django.
لا تتضمن اختبارات ضغط متزامن أو PostgreSQL.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Category, UnitOfMeasure, Product, StockBatch, StockMovement, MovementType
from .services import receive_stock, issue_stock, record_batch_movement


class StockServicesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="store_test_developer",
            password=None,
            is_staff=True,
            is_superuser=True,
        )
        self.category = Category.objects.create(name="Test groceries")
        self.unit = UnitOfMeasure.objects.create(name="Bottle", symbol="bottle")
        self.product = Product.objects.create(
            name="Test oil", category=self.category, unit=self.unit,
            minimum_stock=Decimal("10"),
        )
        self.today = timezone.localdate()
        self.expiry = self.today + timedelta(days=30)

    def receive(self, quantity="20", **kwargs):
        values = {
            "product_id": self.product.pk,
            "quantity": quantity,
            "user": self.user,
            "expiry_date": self.expiry,
        }
        values.update(kwargs)
        return receive_stock(**values)

    def issue(self, quantity, **kwargs):
        values = {
            "product_id": self.product.pk,
            "quantity": quantity,
            "user": self.user,
            "recipient": "Kitchen",
        }
        values.update(kwargs)
        return issue_stock(**values)

    def movement(self, batch, kind, quantity, **kwargs):
        values = {
            "product_id": self.product.pk,
            "batch_id": batch.pk,
            "movement_type": kind,
            "quantity": quantity,
            "user": self.user,
            "reason": "Test reason",
        }
        values.update(kwargs)
        return record_batch_movement(**values)

    def test_receipt_creates_batch_and_stock(self):
        batch = self.receive()
        self.assertEqual(batch.received_quantity, Decimal("20"))
        self.assertEqual(batch.remaining_quantity, Decimal("20"))
        self.assertEqual(self.product.available_stock, Decimal("20"))
        self.assertEqual(batch.movements.count(), 1)

    def test_invalid_dates_do_not_leave_batch(self):
        with self.assertRaises(ValidationError):
            self.receive(production_date=self.today + timedelta(days=1))
        self.assertEqual(StockBatch.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_required_expiry(self):
        with self.assertRaises(ValidationError):
            self.receive(expiry_date=None)

    def test_expired_receipt_rejected(self):
        with self.assertRaises(ValidationError):
            self.receive(expiry_date=self.today - timedelta(days=1))

    def test_expired_opening_balance_is_blocked(self):
        batch = self.receive(
            expiry_date=self.today - timedelta(days=1),
            source=StockBatch.Source.OPENING,
            notes="Opening count; awaiting disposal",
        )
        self.assertTrue(batch.is_blocked)
        self.assertEqual(self.product.current_stock, Decimal("20"))
        self.assertEqual(self.product.available_stock, Decimal("0"))

    def test_whole_unit_rejects_fractions(self):
        with self.assertRaises(ValidationError):
            self.receive(quantity="1.500")

    def test_decimal_unit_accepts_fractions(self):
        unit = UnitOfMeasure.objects.create(
            name="Kilogram", symbol="kg", allow_fractions=True,
        )
        self.product.unit = unit
        self.product.save()
        batch = self.receive(quantity="2.125")
        self.assertEqual(batch.remaining_quantity, Decimal("2.125"))

    def test_invalid_quantities(self):
        for value in ("0", "-1", "NaN", "Infinity", "1.0001", "1000000000", True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.receive(quantity=value)
        self.assertEqual(StockBatch.objects.count(), 0)

    def test_fefo_earlier_expiry_even_when_received_later(self):
        later = self.receive(quantity="10")
        earlier = self.receive(
            quantity="4", expiry_date=self.today + timedelta(days=2),
        )
        lines = self.issue("6")
        self.assertEqual([line.batch_id for line in lines], [earlier.pk, later.pk])
        self.assertEqual(earlier.remaining_quantity, Decimal("0"))
        self.assertEqual(later.remaining_quantity, Decimal("8"))

    def test_undated_batch_comes_last(self):
        self.product.requires_expiry_date = False
        self.product.save()
        undated = self.receive(quantity="10", expiry_date=None)
        dated = self.receive(quantity="3")
        lines = self.issue("4")
        self.assertEqual([line.batch_id for line in lines], [dated.pk, undated.pk])

    def test_insufficient_stock_does_not_partially_issue(self):
        batch = self.receive(quantity="5")
        with self.assertRaises(ValidationError):
            self.issue("6")
        self.assertEqual(batch.remaining_quantity, Decimal("5"))
        self.assertFalse(StockMovement.objects.filter(movement_type=MovementType.ISSUE).exists())

    def test_blocked_batch_not_issued(self):
        batch = self.receive()
        StockBatch.objects.filter(pk=batch.pk).update(is_blocked=True)
        with self.assertRaises(ValidationError):
            self.issue("1")

    def test_expired_batch_not_issued(self):
        batch = self.receive()
        StockBatch.objects.filter(pk=batch.pk).update(
            expiry_date=self.today - timedelta(days=1)
        )
        with self.assertRaises(ValidationError):
            self.issue("1")

    def test_no_recipient_rejected(self):
        self.receive()
        with self.assertRaises(ValidationError):
            self.issue("1", recipient=" ")

    def test_inactive_product_rejected(self):
        self.receive()
        self.product.is_active = False
        self.product.save()
        with self.assertRaises(ValidationError):
            self.issue("1")

    def test_low_stock_threshold(self):
        self.receive()
        self.assertFalse(self.product.is_low_stock)
        self.issue("10")
        self.assertTrue(self.product.is_low_stock)

    def test_waste_reduces_stock(self):
        batch = self.receive()
        self.movement(batch, MovementType.WASTE, "2")
        self.assertEqual(batch.remaining_quantity, Decimal("18"))

    def test_adjustment_cannot_make_negative_stock(self):
        batch = self.receive(quantity="3")
        with self.assertRaises(ValidationError):
            self.movement(batch, MovementType.ADJUST_OUT, "4")
        self.assertEqual(batch.remaining_quantity, Decimal("3"))

    def test_return_cannot_exceed_net_issues(self):
        batch = self.receive()
        self.issue("5")
        self.movement(batch, MovementType.RETURN, "3")
        with self.assertRaises(ValidationError):
            self.movement(batch, MovementType.RETURN, "3")
        self.assertEqual(batch.remaining_quantity, Decimal("18"))

    def test_reason_is_required(self):
        batch = self.receive()
        with self.assertRaises(ValidationError):
            self.movement(batch, MovementType.WASTE, "1", reason="")

    def test_batch_must_belong_to_product(self):
        batch = self.receive()
        other = Product.objects.create(
            name="Other oil", category=self.category, unit=self.unit,
        )
        with self.assertRaises(ValidationError):
            self.movement(batch, MovementType.WASTE, "1", product_id=other.pk)

    def test_unauthorized_user_cannot_write(self):
        user = get_user_model().objects.create_user(
            username="store_test_monk", password=None,
        )
        with self.assertRaises(PermissionDenied):
            self.receive(user=user)

    def test_admin_needs_explicit_stock_permission(self):
        user = get_user_model().objects.create_user(
            username="store_test_admin", password=None,
        )
        user.role = "admin"
        with self.assertRaises(PermissionDenied):
            self.receive(user=user)

        permission = Permission.objects.get(
            content_type__app_label="store", codename="add_stockmovement",
        )
        user.user_permissions.add(permission)
        for key in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(key, None)
        batch = self.receive(user=user)
        self.assertEqual(batch.remaining_quantity, Decimal("20"))

    def test_movement_cannot_be_edited_or_deleted(self):
        batch = self.receive()
        movement = batch.movements.get()
        movement.quantity = Decimal("7")
        with self.assertRaises(ValidationError):
            movement.save()
        with self.assertRaises(ValidationError):
            movement.delete()

    def test_admin_product_list_and_forms(self):
        self.client.force_login(self.user)
        for name, args in (
            ("admin:store_product_changelist", []),
            ("admin:store_product_receive", [self.product.pk]),
            ("admin:store_product_issue", [self.product.pk]),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_admin_receipt_post(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("admin:store_product_receive", args=[self.product.pk]),
            {
                "quantity": "20",
                "received_date": self.today.isoformat(),
                "expiry_date": self.expiry.isoformat(),
                "source": "purchase",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.available_stock, Decimal("20"))

    def test_admin_issue_post(self):
        self.receive()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("admin:store_product_issue", args=[self.product.pk]),
            {"quantity": "7", "recipient": "Kitchen"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product.available_stock, Decimal("13"))

    def test_admin_invalid_receipt_has_errors_not_partial_stock(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("admin:store_product_receive", args=[self.product.pk]),
            {
                "quantity": "1.5",
                "received_date": self.today.isoformat(),
                "expiry_date": self.expiry.isoformat(),
                "source": "purchase",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StockBatch.objects.count(), 0)

    def test_admin_cannot_add_ledger_directly(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:store_stockmovement_add"))
        self.assertEqual(response.status_code, 403)
