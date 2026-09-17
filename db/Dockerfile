# Trasi — db_init one-shot image.
# Il compose viene parso da Coolify, che riscrive i bind mount relativi verso
# /data/coolify/applications/<uuid>/ dove il checkout NON è copiato (misurato:
# /data/coolify/applications/<uuid>./db inesistente → exit 127). Costruire l'immagine
# dal contesto mette i file SQL dentro l'immagine, come lo shim.
FROM postgis/postgis:16-3.4
COPY init-entrypoint.sh /db/init-entrypoint.sh
COPY . /db
