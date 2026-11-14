# Static build served by nginx, which also proxies /api to the API container (one origin for the browser).
FROM node:26.13.0-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
