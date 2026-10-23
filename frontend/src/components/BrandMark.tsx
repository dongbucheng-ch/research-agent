interface BrandMarkProps {
  className?: string
}

export default function BrandMark({ className }: BrandMarkProps) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="10" cy="10" r="2.2" fill="currentColor" />
      <path
        d="M4.6 4.6a7.6 7.6 0 0 0 0 10.8"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M15.4 4.6a7.6 7.6 0 0 1 0 10.8"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M7.35 7.35a3.8 3.8 0 0 0 0 5.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M12.65 7.35a3.8 3.8 0 0 1 0 5.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  )
}
