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

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html

ENV PORT=80 \
    API_UPSTREAM=http://api:9247 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    NGINX_ENVSUBST_FILTER="^(PORT|API_UPSTREAM|NGINX_LOCAL_RESOLVERS)$"

COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80
