FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# empty VITE_API = relative URLs; nginx proxies /api,/tiles,/healthz to backend
ARG VITE_API=""
ENV VITE_API=$VITE_API
RUN npm run build

FROM nginx:alpine
# envsubst renders the template at container start; compose keeps these defaults,
# PORT and BACKEND_URL can be injected at runtime
ENV PORT=3000 BACKEND_URL=http://server:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
