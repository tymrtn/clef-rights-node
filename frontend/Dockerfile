FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE=/api
ARG VITE_DEMO_MODE=false
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_DEMO_MODE=$VITE_DEMO_MODE
RUN npm run build

# Stable release reviewed 2026-09-18: https://nginx.org/en/CHANGES-1.30
# Pin the multi-platform manifest; review vendor advisories when updating it.
FROM nginx:1.30.5-alpine@sha256:a5f2157a0302eb0c5e300415effb63a9e70ed1eb9c107283819bf6d149ab607c
COPY --from=build /app/dist /usr/share/nginx/html

ENV PORT=80 \
    API_UPSTREAM=http://api:9247 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    NGINX_ENVSUBST_FILTER="^(PORT|API_UPSTREAM|NGINX_LOCAL_RESOLVERS)$"

COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80
