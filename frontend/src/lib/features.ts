/**
 * The style guide is for the team. It is available while developing and in any build made with
 * VITE_ENABLE_STYLEGUIDE=true (used to audit it), and hidden from production builds.
 */
export const showStyleguide: boolean =
  import.meta.env.DEV || import.meta.env.VITE_ENABLE_STYLEGUIDE === 'true'
