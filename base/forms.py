# forms.py
from django import forms
from .models import Inventory
import re

class InventoryForm(forms.ModelForm):
    link = forms.URLField(label="Link do Inventário")

    class Meta:
        model = Inventory
        fields = ["name", "link"]

    def clean(self):
        cleaned_data = super().clean()
        link = cleaned_data.get("link")

        # tenta extrair steam_id
        match = re.search(r"/profiles/(\d+)/", link)
        if match:
            cleaned_data["steam_id"] = match.group(1)
        else:
            raise forms.ValidationError("Não consegui extrair o SteamID do link.")

        return cleaned_data
