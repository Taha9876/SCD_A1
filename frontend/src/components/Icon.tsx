/**
 * Inline SVG icons.
 *
 * Inline rather than an icon font or a package: these are ~15 shapes, they
 * inherit currentColor, they need no network request, and nothing gets pulled
 * into the bundle that we did not write.
 *
 * Every icon is decorative by default (aria-hidden) because it always sits
 * beside a real word. That pairing is deliberate -- it is what lets priority
 * and status survive colour-blindness, greyscale print and forced-colors.
 */
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { title?: string }

function Svg({ title, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      focusable="false"
      {...rest}
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  )
}

export const IconAlert = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
  </Svg>
)

export const IconInfo = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 16v-4M12 8h.01" />
  </Svg>
)

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="m8.5 12.5 2.5 2.5 4.5-5" />
  </Svg>
)

export const IconMinus = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8.5 12h7" />
  </Svg>
)

export const IconClose = (p: IconProps) => (
  <Svg {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Svg>
)

export const IconSun = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Svg>
)

export const IconMoon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </Svg>
)

export const IconSend = (p: IconProps) => (
  <Svg {...p}>
    <path d="M22 2 11 13" />
    <path d="M22 2 15 22l-4-9-9-4Z" />
  </Svg>
)

export const IconList = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
  </Svg>
)

export const IconChart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 3v18h18" />
    <path d="M7 15v3M12 9v9M17 5v13" />
  </Svg>
)

export const IconInbox = (p: IconProps) => (
  <Svg {...p}>
    <path d="M22 12h-6l-2 3h-4l-2-3H2" />
    <path d="M5.4 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.4-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.8 1.1Z" />
  </Svg>
)

export const IconPin = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
    <circle cx="12" cy="10" r="3" />
  </Svg>
)

export const IconClock = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </Svg>
)

export const IconCopy = (p: IconProps) => (
  <Svg {...p}>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </Svg>
)

export const IconRefresh = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 12a9 9 0 1 1-2.6-6.4" />
    <path d="M21 3v6h-6" />
  </Svg>
)

export const IconDatabase = (p: IconProps) => (
  <Svg {...p}>
    <ellipse cx="12" cy="5" rx="8" ry="3" />
    <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
    <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
  </Svg>
)

export const IconBolt = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" />
  </Svg>
)

/** The brand mark: a droplet with a pulse line through it. */
export const IconBrand = (p: IconProps) => (
  <svg viewBox="0 0 32 32" fill="none" aria-hidden focusable="false" {...p}>
    <path
      d="M16 3.5c5.2 5.6 8.5 9.9 8.5 14a8.5 8.5 0 0 1-17 0c0-4.1 3.3-8.4 8.5-14Z"
      fill="currentColor"
      opacity="0.14"
    />
    <path
      d="M16 3.5c5.2 5.6 8.5 9.9 8.5 14a8.5 8.5 0 0 1-17 0c0-4.1 3.3-8.4 8.5-14Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinejoin="round"
    />
    <path
      d="M9.5 18.2h3l1.8-3.6 2.4 6 1.7-2.4h3.1"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
)

/* --- Category icons ---------------------------------------------------- */

export const IconDroplet = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.5c3.9 4.3 6.4 7.6 6.4 10.7a6.4 6.4 0 0 1-12.8 0c0-3.1 2.5-6.4 6.4-10.7Z" />
  </Svg>
)

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
    <path d="M10 11v5M14 11v5" />
  </Svg>
)

export const IconRoad = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 21 10 3M17 21 14 3" />
    <path d="M12 6v2M12 11v2M12 16v2" />
  </Svg>
)

export const IconLamp = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 21h6M12 21V10" />
    <path d="M12 10a4 4 0 0 0 4-4H8a4 4 0 0 0 4 4Z" />
    <path d="M12 2v2" />
  </Svg>
)

export const IconDots = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="6" cy="12" r="1.2" />
    <circle cx="12" cy="12" r="1.2" />
    <circle cx="18" cy="12" r="1.2" />
  </Svg>
)

export const IconArrowLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="M19 12H5M11 18l-6-6 6-6" />
  </Svg>
)

export const IconUser = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </Svg>
)

export const IconExternal = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 4h6v6M20 4 10 14" />
    <path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" />
  </Svg>
)
