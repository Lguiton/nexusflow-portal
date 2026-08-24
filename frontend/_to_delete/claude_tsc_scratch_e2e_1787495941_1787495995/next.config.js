/** @type {import('next').NextConfig} */
const nextConfig = {
  // Explicitly define workspace root for Turbopack to prevent lockfile warnings
  turbopack: {
    root: '/mnt/c/Users/Guito/nexusflow-portal',
  },
};

module.exports = nextConfig;
