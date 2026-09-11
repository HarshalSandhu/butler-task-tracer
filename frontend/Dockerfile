FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json ./
# npm install, not npm ci: the lockfile was generated on macOS and its
# platform-conditional optional deps (e.g. @emnapi/*) don't match what
# this Linux container needs - npm ci is strict about that mismatch,
# npm install resolves it correctly for the actual build platform.
RUN npm install
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
