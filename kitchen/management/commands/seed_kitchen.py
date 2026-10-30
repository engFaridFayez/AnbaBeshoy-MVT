from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from kitchen.models import (
    DailyMenu,
    DailyMenuItem,
    ItemCategory,
    MealType,
    MenuItem,
)


class Command(BaseCommand):
    help = "Seed demo kitchen menus and menu items"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "بدء إضافة بيانات تجريبية للمطبخ..."
            )
        )

        # ==========================================
        # Menu Items
        # ==========================================

        menu_items_data = [
            # --------------------------
            # Food
            # --------------------------
            {
                "name": "فول",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "بيض",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "جبنة بيضاء",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "طعمية",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "مربى",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "عسل",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "أرز",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "مكرونة",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "فراخ",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "لحمة",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "خضار",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "بطاطس",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "سلطة",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "شوربة",
                "category": ItemCategory.FOOD,
            },
            {
                "name": "جبنة رومي",
                "category": ItemCategory.FOOD,
            },

            # --------------------------
            # Drinks
            # --------------------------
            {
                "name": "شاي",
                "category": ItemCategory.DRINKS,
            },
            {
                "name": "قهوة",
                "category": ItemCategory.DRINKS,
            },
            {
                "name": "لبن",
                "category": ItemCategory.DRINKS,
            },
            {
                "name": "عصير برتقال",
                "category": ItemCategory.DRINKS,
            },

            # --------------------------
            # Dessert
            # --------------------------
            {
                "name": "فاكهة",
                "category": ItemCategory.DESSERT,
            },
            {
                "name": "أرز باللبن",
                "category": ItemCategory.DESSERT,
            },
            {
                "name": "مهلبية",
                "category": ItemCategory.DESSERT,
            },
            {
                "name": "كيك",
                "category": ItemCategory.DESSERT,
            },
        ]

        items = {}

        for item_data in menu_items_data:
            item, created = MenuItem.objects.update_or_create(
                name=item_data["name"],
                category=item_data["category"],
                defaults={
                    "is_active": True,
                },
            )

            items[item.name] = item

            if created:
                self.stdout.write(
                    f"+ تم إنشاء الصنف: {item.name}"
                )

        # ==========================================
        # Menus
        # ==========================================

        today = timezone.localdate()

        menu_schedule = [
            # ======================================
            # Today
            # ======================================

            {
                "date": today,
                "meal_type": MealType.BREAKFAST,
                "deadline_hour": 8,
                "deadline_minute": 30,
                "items": [
                    "فول",
                    "طعمية",
                    "بيض",
                    "جبنة بيضاء",
                    "مربى",
                    "شاي",
                    "لبن",
                ],
            },

            {
                "date": today,
                "meal_type": MealType.LUNCH,
                "deadline_hour": 12,
                "deadline_minute": 0,
                "items": [
                    "فراخ",
                    "أرز",
                    "خضار",
                    "سلطة",
                    "شوربة",
                    "فاكهة",
                    "عصير برتقال",
                ],
            },

            {
                "date": today,
                "meal_type": MealType.DINNER,
                "deadline_hour": 18,
                "deadline_minute": 0,
                "items": [
                    "جبنة بيضاء",
                    "جبنة رومي",
                    "بيض",
                    "بطاطس",
                    "شاي",
                    "مهلبية",
                ],
            },

            # ======================================
            # Tomorrow
            # ======================================

            {
                "date": today + timedelta(days=1),
                "meal_type": MealType.BREAKFAST,
                "deadline_hour": 8,
                "deadline_minute": 30,
                "items": [
                    "فول",
                    "بيض",
                    "جبنة بيضاء",
                    "عسل",
                    "شاي",
                    "قهوة",
                ],
            },

            {
                "date": today + timedelta(days=1),
                "meal_type": MealType.LUNCH,
                "deadline_hour": 12,
                "deadline_minute": 0,
                "items": [
                    "لحمة",
                    "مكرونة",
                    "بطاطس",
                    "سلطة",
                    "شوربة",
                    "أرز باللبن",
                ],
            },

            {
                "date": today + timedelta(days=1),
                "meal_type": MealType.DINNER,
                "deadline_hour": 18,
                "deadline_minute": 0,
                "items": [
                    "جبنة بيضاء",
                    "بيض",
                    "طعمية",
                    "شاي",
                    "كيك",
                ],
            },
        ]

        # ==========================================
        # Create Daily Menus
        # ==========================================

        for menu_data in menu_schedule:

            menu_date = menu_data["date"]

            deadline_naive = datetime.combine(
                menu_date,
                time(
                    hour=menu_data["deadline_hour"],
                    minute=menu_data["deadline_minute"],
                ),
            )

            deadline = timezone.make_aware(
                deadline_naive,
                timezone.get_current_timezone(),
            )

            daily_menu, created = DailyMenu.objects.update_or_create(
                date=menu_date,
                meal_type=menu_data["meal_type"],
                defaults={
                    "is_published": True,
                    "ordering_deadline": deadline,
                },
            )

            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"+ قائمة جديدة: {daily_menu}"
                    )
                )
            else:
                self.stdout.write(
                    f"~ تحديث القائمة: {daily_menu}"
                )

            # ======================================
            # Add items to Daily Menu
            # ======================================

            wanted_item_ids = []

            for item_name in menu_data["items"]:
                item = items[item_name]

                wanted_item_ids.append(item.pk)

                DailyMenuItem.objects.update_or_create(
                    daily_menu=daily_menu,
                    item=item,
                    defaults={
                        "is_available": True,
                    },
                )

            # Remove old seeded menu entries
            # that are no longer part of this menu
            DailyMenuItem.objects.filter(
                daily_menu=daily_menu,
            ).exclude(
                item_id__in=wanted_item_ids,
            ).delete()

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "تم إنشاء بيانات المطبخ التجريبية بنجاح ✅"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"تم تجهيز قوائم يوم {today} "
                f"ويوم {today + timedelta(days=1)}"
            )
        )