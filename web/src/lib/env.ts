/**
 * Build-time switches (set in web/.env.local or the host's build settings; see docs/deploy.md).
 * Both default to off, which is the friends-only launch: no ad boxes, no feedback link.
 */
export const ADS_ON = import.meta.env.VITE_ADS === 'true'

/** True once Cloudflare Web Analytics is switched on for the site, so the Privacy page says so. */
export const ANALYTICS_ON = import.meta.env.VITE_ANALYTICS === 'true'

/** A mailto: link or a form URL for the footer's "Send feedback". Empty hides the link. */
export const FEEDBACK_URL: string = (import.meta.env.VITE_FEEDBACK_URL as string | undefined) ?? ''
