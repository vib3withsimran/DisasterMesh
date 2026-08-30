/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow mapbox-gl wasm on some browsers
  webpack: (config) => {
    config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false };
    return config;
  },
};

module.exports = nextConfig;
