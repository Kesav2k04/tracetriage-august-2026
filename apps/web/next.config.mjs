/**
 * Static export, deliberately.
 *
 * The plan's reason for a static console is that nothing can break in front of a
 * judge because a backend went down. That property is worth more than any feature
 * a server would add here, so there is no server: no API routes, no image
 * optimisation service, no runtime data fetching, no credentials to leak. The
 * whole site is files.
 *
 * Consequences accepted on purpose:
 *   - next/image's optimiser is off, so imagery is pre-sized by
 *     scripts/build_console_data.py, which is where the intensity decision lives
 *     anyway.
 *   - dynamic routes are enumerated at build time by generateStaticParams.
 *   - trailing slashes are on, so every route is a directory with an index.html
 *     and any static host serves it without rewrite rules.
 */
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  productionBrowserSourceMaps: false,
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
