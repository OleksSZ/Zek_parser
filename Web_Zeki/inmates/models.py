from django.db import models


class Inmate(models.Model):
    id = models.IntegerField(primary_key=True)
    booking_no = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    age = models.CharField(max_length=10, blank=True, null=True)
    arrest_date = models.CharField(max_length=30, blank=True, null=True)
    arrest_time = models.CharField(max_length=20, blank=True, null=True)
    sex = models.CharField(max_length=20, blank=True, null=True)
    dob = models.CharField(max_length=30, blank=True, null=True)
    height = models.CharField(max_length=20, blank=True, null=True)
    weight = models.CharField(max_length=20, blank=True, null=True)
    eye_color = models.CharField(max_length=30, blank=True, null=True)
    hair_color = models.CharField(max_length=30, blank=True, null=True)
    arrest_agency = models.CharField(max_length=255, blank=True, null=True)
    housing_facility = models.CharField(max_length=255, blank=True, null=True)
    arrest_location = models.CharField(max_length=255, blank=True, null=True)
    release_date = models.CharField(max_length=30, blank=True, null=True)
    released_to = models.CharField(max_length=50, blank=True, null=True)
    bailable = models.CharField(max_length=50, blank=True, null=True)
    jail_type = models.CharField(max_length=20, blank=True, null=True)
    raw_json = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False            # Django не создаёт/не меняет эту таблицу
        db_table = "inmates"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.booking_no} — {self.name}"