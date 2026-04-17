FROM node:22-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY package.json package-lock.json ./
RUN npm ci

# Copy application code
COPY . .

RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
