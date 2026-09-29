from django.contrib import admin
from .models import Inmate


@admin.register(Inmate)
class InmateAdmin(admin.ModelAdmin):
    list_display = (
        "booking_no", "name", "age", "sex",
        "arrest_date", "arrest_time",
        "housing_facility", "release_date",
    )
    list_filter = ("sex", "housing_facility", "jail_type", "bailable")
    search_fields = ("booking_no", "name", "housing_facility", "arrest_agency")
    ordering = ("-id",)
    list_per_page = 50
    date_hierarchy = None

    readonly_fields = (
        "booking_no", "name", "age", "arrest_date", "arrest_time",
        "sex", "dob", "height", "weight", "eye_color", "hair_color",
        "arrest_agency", "housing_facility", "arrest_location",
        "release_date", "released_to", "bailable", "jail_type",
        "raw_json", "created_at", "updated_at",
    )

    # Только просмотр — никаких добавлений/изменений/удалений
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False