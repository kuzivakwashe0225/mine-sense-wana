export function Logo({ size = 36 }) {
  return (
    <span className="logo" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 32 32"><path d="M6 24 13 9l5 9 3-5 5 11z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" /><circle cx="21" cy="13" r="2.6" fill="#E58456" /></svg>
    </span>
  )
}
