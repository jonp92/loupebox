# Runs on the builder's own platform: the output is static files, and npm ci under QEMU emulation (multi-arch
# release builds) takes tens of minutes. Only the nginx stage below is built per target platform.
FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/security-headers.conf /etc/nginx/security-headers.conf
COPY --chmod=755 docker/40-config.sh /docker-entrypoint.d/40-config.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
ENV API_URL=http://localhost:8000
