# Trasi — Home statica come immagine (modalità Coolify).
# Costruire dal checkout garantisce che l'anteprima PR serva il contenuto del suo branch:
# un bind mount ./home sotto Coolify punta a /data/coolify/applications/<uuid>/ dove il
# contenuto del repo non viene copiato (misurato: home-pr-4 vuota → 403 + unhealthy).
FROM nginx:1.25.5-alpine
COPY . /usr/share/nginx/html
