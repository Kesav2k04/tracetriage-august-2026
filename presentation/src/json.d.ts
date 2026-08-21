/**
 * The receipts are imported as data, not as types.
 *
 * With `resolveJsonModule` on, tsc parses and types all 2.3 MB of
 * DATASET_MANIFEST.json on every check, which is slow and buys nothing: the shape
 * of a receipt is asserted by test/claims.test.ts against the file on disk, which
 * is a stronger check than a structural type inferred from the same file.
 */
declare module "*.json" {
  const value: unknown;
  export default value;
}
