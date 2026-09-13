import os

from django import forms
from django.conf import settings


class ERPUploadForm(forms.Form):
    excel_file = forms.FileField(
        label="ERP Excel file",
        help_text="Only Excel files (.xlsx, .xls) are accepted.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.xls"}),
    )

    def clean_excel_file(self):
        f = self.cleaned_data["excel_file"]
        ext = os.path.splitext(f.name)[1].lower()
        allowed = settings.ALLOWED_EXCEL_EXTENSIONS
        if ext not in allowed:
            raise forms.ValidationError(
                f"'{ext or 'this file'}' is not allowed. "
                f"Please upload an Excel file ({', '.join(allowed)})."
            )
        return f
