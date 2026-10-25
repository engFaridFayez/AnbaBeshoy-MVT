"""Seed rich Arabic demo data for the store app."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from store.demo_seed_data import CATEGORIES, PRODUCTS, SUPPLIERS, UNITS
from store.models import (
    AlertType,
    Category,
    Product,
    StockAlert,
    StockBatch,
    UnitOfMeasure,
)
from store.services import issue_stock, receive_stock


class Command(BaseCommand):
    help = "إنشاء بيانات عربية تجريبية كبيرة للمخزن: أقسام ووحدات ومنتجات وأرصدة ودفعات وتنبيهات."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            help="اسم مستخدم موجود ليُسجل باسمِه الوارد والصرف. يفضّل superadmin.",
        )
        parser.add_argument(
            "--products-only",
            action="store_true",
            help="إنشاء الأقسام والوحدات والمنتجات فقط بدون دفعات أو حركات أو تنبيهات.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        actor = self._get_actor(options.get("username"))
        products_only = options["products_only"]

        self.stdout.write(self.style.MIGRATE_HEADING("بدء Seed المخزن بالعربية..."))

        categories = self._seed_categories()
        units = self._seed_units()
        products = self._seed_products(categories, units)

        stats = {
            "categories": len(categories),
            "units": len(units),
            "products": len(products),
            "batches": 0,
            "issues": 0,
            "alerts": 0,
        }

        if not products_only:
            batch_count, issue_count = self._seed_stock(products, actor)
            stats["batches"] = batch_count
            stats["issues"] = issue_count
            stats["alerts"] = self._seed_alerts(products)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("تم إنشاء بيانات المخزن التجريبية بنجاح."))
        self.stdout.write(f"الأقسام: {stats['categories']}")
        self.stdout.write(f"الوحدات: {stats['units']}")
        self.stdout.write(f"المنتجات: {stats['products']}")
        if not products_only:
            self.stdout.write(f"دفعات التوريد التي أضيفت الآن: {stats['batches']}")
            self.stdout.write(f"عمليات الصرف التي أضيفت الآن: {stats['issues']}")
            self.stdout.write(f"تنبيهات المخزن المفتوحة: {stats['alerts']}")
            self.stdout.write("")
            self.stdout.write("ستجد أمثلة لمخزون طبيعي، ومخزون منخفض، ودفعات قريبة الانتهاء، ودفعات منتهية وموقوفة.")

    def _get_actor(self, username):
        User = get_user_model()

        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist as exc:
                raise CommandError(f"لا يوجد مستخدم باسم: {username}") from exc

            if not user.is_active:
                raise CommandError("المستخدم المحدد غير نشط.")

            if not (user.is_superuser or getattr(user, "role", "") == "superadmin"):
                raise CommandError(
                    "استخدم حساب superadmin / superuser حتى تسمح خدمة المخزن بتسجيل الحركات."
                )
            return user

        user = User.objects.filter(is_active=True, is_superuser=True).order_by("pk").first()
        if user:
            return user

        user = User.objects.filter(is_active=True, role="superadmin").order_by("pk").first()
        if user:
            return user

        # حساب داخلي غير قابل للدخول، فقط لتوثيق بيانات الـ seed عندما تكون القاعدة فارغة.
        field_names = {field.name for field in User._meta.fields}
        create_kwargs = {
            "username": "store_seed_operator",
            "is_active": True,
            "is_staff": True,
            "is_superuser": True,
        }
        if "role" in field_names:
            create_kwargs["role"] = "superadmin"
        if "display_name" in field_names:
            create_kwargs["display_name"] = "مستخدم Seed للمخزن"

        user, created = User.objects.get_or_create(
            username="store_seed_operator",
            defaults=create_kwargs,
        )
        if created:
            user.set_unusable_password()
            user.save()
            self.stdout.write(
                self.style.WARNING(
                    "لم يوجد Superuser؛ تم إنشاء store_seed_operator بكلمة مرور غير قابلة للاستخدام لتوثيق بيانات التجربة فقط."
                )
            )
        return user

    def _seed_categories(self):
        result = {}
        for name, description, sort_order in CATEGORIES:
            obj, _ = Category.objects.update_or_create(
                name=name,
                defaults={
                    "description": description,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            result[name] = obj
        return result

    def _seed_units(self):
        result = {}

        for name, symbol, allow_fractions in UNITS:
            # الأولوية للرمز لأنه المفتاح المستخدم داخل بيانات المنتجات.
            # لو لم نجده، نبحث بالاسم لتفادي كسر unique(name).
            obj = UnitOfMeasure.objects.filter(symbol=symbol).first()
            if obj is None:
                obj = UnitOfMeasure.objects.filter(name=name).first()

            if obj is None:
                obj = UnitOfMeasure.objects.create(
                    name=name,
                    symbol=symbol,
                    allow_fractions=allow_fractions,
                    is_active=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"تم إنشاء وحدة: {obj.name} ({obj.symbol})"
                    )
                )
            else:
                # لا نغيّر الاسم/الرمز/سياسة الكسور لو الوحدة مستخدمة بالفعل،
                # لأن الموديل يحمي تاريخ المخزون من التعديل بأثر رجعي.
                if not obj.is_active:
                    obj.is_active = True
                    obj.save(update_fields=["is_active"])

                if (
                    obj.name != name
                    or obj.symbol != symbol
                    or obj.allow_fractions != allow_fractions
                ):
                    self.stdout.write(
                        self.style.WARNING(
                            "تم استخدام وحدة موجودة كما هي بدل تعديل تعريفها: "
                            f"{obj.name} ({obj.symbol}) "
                            f"← مطلوبة في الـ Seed كـ {name} ({symbol})"
                        )
                    )
                else:
                    self.stdout.write(
                        f"الوحدة موجودة بالفعل: {obj.name} ({obj.symbol})"
                    )

            # مهم: المنتجات في ملف البيانات تبحث بالرمز الموجود في UNITS،
            # لذلك نربط هذا الرمز بالوحدة التي وجدناها/أنشأناها.
            result[symbol] = obj

        return result

    def _seed_products(self, categories, units):
        result = []
        barcode_counter = 1

        for (
            name,
            category_name,
            unit_symbol,
            minimum_stock,
            requires_expiry,
            warning_days,
            has_barcode,
        ) in PRODUCTS:
            category = categories[category_name]
            desired_unit = units[unit_symbol]

            barcode = None
            if has_barcode:
                barcode = f"6221000{barcode_counter:06d}"
                barcode_counter += 1

            product = Product.objects.filter(
                category=category,
                name=name,
            ).first()

            if product is None:
                # لو باركود الـ demo مستخدم مسبقًا، ننشئ المنتج من غير باركود
                # بدل ما نفشل الـ Seed كله.
                if barcode and Product.objects.filter(barcode=barcode).exists():
                    barcode = None

                product = Product.objects.create(
                    category=category,
                    name=name,
                    unit=desired_unit,
                    minimum_stock=Decimal(str(minimum_stock)),
                    requires_expiry_date=requires_expiry,
                    expiry_warning_days=warning_days,
                    barcode=barcode,
                    is_active=True,
                    description="بيانات تجريبية عربية لاختبار نظام المخزن.",
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"تم إنشاء المنتج: {product.name}"
                    )
                )

            else:
                has_stock_history = product.batches.exists()
                changed_fields = []

                # تغيير الوحدة مسموح فقط قبل وجود دفعات.
                if product.unit_id != desired_unit.id:
                    if has_stock_history:
                        self.stdout.write(
                            self.style.WARNING(
                                "تم الاحتفاظ بوحدة المنتج القديمة لأن له دفعات: "
                                f"{product.name} ({product.unit.symbol})"
                            )
                        )
                    else:
                        product.unit = desired_unit
                        changed_fields.append("unit")

                new_minimum = Decimal(str(minimum_stock))
                if product.minimum_stock != new_minimum:
                    product.minimum_stock = new_minimum
                    changed_fields.append("minimum_stock")

                # سياسة إلزام الصلاحية نتركها كما هي لو للمنتج تاريخ مخزني،
                # حتى لا نغير معنى دفعات قديمة.
                if (
                    not has_stock_history
                    and product.requires_expiry_date != requires_expiry
                ):
                    product.requires_expiry_date = requires_expiry
                    changed_fields.append("requires_expiry_date")

                if product.expiry_warning_days != warning_days:
                    product.expiry_warning_days = warning_days
                    changed_fields.append("expiry_warning_days")

                # لا نستبدل باركود حقيقي موجود. نملأه فقط إن كان فارغًا
                # وكان باركود الـ demo غير مستخدم في منتج آخر.
                if not product.barcode and barcode:
                    barcode_used = Product.objects.exclude(
                        pk=product.pk
                    ).filter(barcode=barcode).exists()
                    if not barcode_used:
                        product.barcode = barcode
                        changed_fields.append("barcode")

                if not product.is_active:
                    product.is_active = True
                    changed_fields.append("is_active")

                if not product.description:
                    product.description = (
                        "بيانات تجريبية عربية لاختبار نظام المخزن."
                    )
                    changed_fields.append("description")

                if changed_fields:
                    product.save(update_fields=changed_fields)
                    self.stdout.write(
                        self.style.WARNING(
                            f"تم تحديث البيانات الآمنة للمنتج: {product.name}"
                        )
                    )
                else:
                    self.stdout.write(
                        f"المنتج موجود بالفعل: {product.name}"
                    )

            result.append(product)

        return result

    def _seed_stock(self, products, actor):
        today = timezone.localdate()
        batch_count = 0
        issue_count = 0

        for index, product in enumerate(products, start=1):
            # عدم تكرار الدفعات عند إعادة تشغيل الأمر.
            seed_reference = f"SEED-{product.code}"
            if product.batches.filter(reference__startswith=seed_reference).exists():
                continue

            mode = index % 6
            minimum = Decimal(product.minimum_stock)
            whole = not product.unit.allow_fractions

            def qty(value):
                value = Decimal(str(value))
                if whole:
                    return value.quantize(Decimal("1"))
                return value.quantize(Decimal("0.001"))

            received_date = today - timedelta(days=(index % 10) + 1)
            production_date = received_date - timedelta(days=2)
            supplier = SUPPLIERS[index % len(SUPPLIERS)]
            source = (
                StockBatch.Source.DONATION
                if index % 7 == 0
                else StockBatch.Source.PURCHASE
            )

            # 0: طبيعي
            if mode == 0:
                received = qty(max(minimum * 4, Decimal("20")))
                expiry = today + timedelta(days=120)
                self._receive(
                    product, received, actor, received_date, production_date,
                    expiry, source, supplier, seed_reference + "-A"
                )
                target = qty(max(minimum * 2, Decimal("8")))
                issue = received - target
                if issue > 0:
                    issue_stock(
                        product_id=product.pk,
                        quantity=issue,
                        user=actor,
                        recipient="المطبخ - بيانات تجريبية",
                        reference=seed_reference + "-ISSUE",
                        notes="صرف تجريبي لإنشاء رصيد طبيعي.",
                    )
                    issue_count += 1
                batch_count += 1

            # 1: منخفض عند الحد الأدنى أو أقل
            elif mode == 1:
                received = qty(max(minimum * 3, Decimal("15")))
                expiry = today + timedelta(days=75)
                self._receive(
                    product, received, actor, received_date, production_date,
                    expiry, source, supplier, seed_reference + "-A"
                )
                target = qty(minimum)
                issue = received - target
                if issue > 0:
                    issue_stock(
                        product_id=product.pk,
                        quantity=issue,
                        user=actor,
                        recipient="المطبخ - بيانات تجريبية",
                        reference=seed_reference + "-ISSUE",
                        notes="صرف تجريبي لإظهار حالة المخزون المنخفض.",
                    )
                    issue_count += 1
                batch_count += 1

            # 2: دفعة قريبة الانتهاء
            elif mode == 2:
                received = qty(max(minimum * 2, Decimal("12")))
                expiry = today + timedelta(days=max(1, min(product.expiry_warning_days, 3)))
                self._receive(
                    product, received, actor, received_date, production_date,
                    expiry, source, supplier, seed_reference + "-A"
                )
                batch_count += 1

            # 3: دفعتان بصلاحيتين مختلفتين
            elif mode == 3:
                first = qty(max(minimum + Decimal("4"), Decimal("10")))
                second = qty(max(minimum * 2, Decimal("15")))
                self._receive(
                    product, first, actor, received_date, production_date,
                    today + timedelta(days=max(2, min(product.expiry_warning_days, 5))),
                    source, supplier, seed_reference + "-A"
                )
                self._receive(
                    product, second, actor, today - timedelta(days=1), today - timedelta(days=3),
                    today + timedelta(days=100),
                    StockBatch.Source.PURCHASE, "شركة النيل للتوريدات", seed_reference + "-B"
                )
                batch_count += 2
                partial_issue = qty(max(Decimal("1"), first / Decimal("2")))
                if partial_issue > 0:
                    issue_stock(
                        product_id=product.pk,
                        quantity=partial_issue,
                        user=actor,
                        recipient="المطبخ - بيانات تجريبية",
                        reference=seed_reference + "-ISSUE",
                        notes="صرف تجريبي لاختبار الصرف من الأقرب انتهاءً.",
                    )
                    issue_count += 1

            # 4: دفعة منتهية موقوفة + دفعة سليمة
            elif mode == 4:
                expired_qty = qty(max(minimum, Decimal("6")))
                self._receive(
                    product, expired_qty, actor,
                    today - timedelta(days=60), today - timedelta(days=90),
                    today - timedelta(days=2),
                    StockBatch.Source.OPENING,
                    "رصيد افتتاحي تجريبي",
                    seed_reference + "-EXPIRED",
                    notes="دفعة منتهية تجريبية لإظهار تنبيه الصلاحية.",
                )
                valid_qty = qty(max(minimum * 2, Decimal("12")))
                self._receive(
                    product, valid_qty, actor,
                    today - timedelta(days=2), today - timedelta(days=4),
                    today + timedelta(days=80),
                    StockBatch.Source.PURCHASE,
                    supplier,
                    seed_reference + "-VALID",
                )
                batch_count += 2

            # 5: بدون مخزون - لا توجد دفعات، لاختبار حالة النفاد
            else:
                continue

        return batch_count, issue_count

    def _receive(
        self,
        product,
        quantity,
        actor,
        received_date,
        production_date,
        expiry_date,
        source,
        supplier,
        reference,
        notes="",
    ):
        # للمنتجات التي لا تتطلب صلاحية، نحتفظ بتاريخ انتهاء تجريبي فقط لو منطقي.
        if not product.requires_expiry_date and expiry_date:
            # المنتجات الطازجة والمخبوزات تستفيد من اختبار قرب الصلاحية أيضًا.
            pass

        return receive_stock(
            product_id=product.pk,
            quantity=quantity,
            user=actor,
            received_date=received_date,
            production_date=production_date,
            expiry_date=expiry_date,
            source=source,
            supplier_name=supplier,
            supplier_batch_number=f"LOT-{reference[-8:]}",
            reference=reference,
            storage_location=product.category.name,
            notes=notes or "دفعة تجريبية تم إنشاؤها بواسطة seed_store_demo.",
        )

    def _seed_alerts(self, products):
        today = timezone.localdate()

        for product in products:
            if product.is_low_stock:
                StockAlert.objects.get_or_create(
                    product=product,
                    batch=None,
                    alert_type=AlertType.LOW_STOCK,
                    resolved_at=None,
                    defaults={
                        "message": (
                            f"المخزون المتاح من {product.name} وصل إلى "
                            f"{product.available_stock} {product.unit.symbol}، "
                            f"والحد الأدنى {product.minimum_stock} {product.unit.symbol}."
                        )
                    },
                )

            for batch in product.batches.all():
                if batch.remaining_quantity <= 0 or not batch.expiry_date:
                    continue

                if batch.expiry_date < today:
                    alert_type = AlertType.EXPIRED
                    message = (
                        f"توجد دفعة من {product.name} منتهية الصلاحية بتاريخ "
                        f"{batch.expiry_date:%Y-%m-%d}."
                    )
                elif batch.is_expiring_soon:
                    alert_type = AlertType.EXPIRING
                    message = (
                        f"دفعة {product.name} تقترب من انتهاء الصلاحية بتاريخ "
                        f"{batch.expiry_date:%Y-%m-%d}."
                    )
                else:
                    continue

                existing = StockAlert.objects.filter(
                    batch=batch,
                    resolved_at=None,
                ).first()
                if existing:
                    if existing.alert_type != alert_type or existing.message != message:
                        existing.alert_type = alert_type
                        existing.message = message
                        existing.save(update_fields=["alert_type", "message"])
                else:
                    StockAlert.objects.create(
                        product=product,
                        batch=batch,
                        alert_type=alert_type,
                        message=message,
                    )

        return StockAlert.objects.filter(resolved_at__isnull=True).count()
