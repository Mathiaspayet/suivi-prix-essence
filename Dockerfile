# Image légère : la variante « slim » suffit, aucune compilation n'est requise.
FROM python:3.11-slim

# Fuseau horaire, pour que la collecte se déclenche à l'heure française.
ENV TZ=Europe/Paris \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /application

# Les dépendances sont installées avant le code : tant que requirements.txt ne
# change pas, Docker réutilise cette étape et la reconstruction est immédiate.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY carburants/ ./carburants/
COPY scripts/ ./scripts/

# Les données vivent dans un volume, afin de survivre à une mise à jour de l'image.
VOLUME ["/application/donnees"]
EXPOSE 8000

CMD ["uvicorn", "carburants.web.app:application", "--host", "0.0.0.0", "--port", "8000"]
