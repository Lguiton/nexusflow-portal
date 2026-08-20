# Use official lightweight Node image
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first
COPY package.json package-lock.json* ./
RUN npm ci

# Copy the rest of the frontend code
COPY . .

# Force a clean build without Turbopack
RUN npx next build

# Stage 2: Production Server
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
# Disable Next.js Telemetry inside the container
ENV NEXT_TELEMETRY_DISABLED=1

# Copy built assets from builder stage
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

# Start the Next.js production server
CMD ["node", "server.js"]
