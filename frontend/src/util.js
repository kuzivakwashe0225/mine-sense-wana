export const initials = (name = '') => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?'
export const minutes = (sec) => { const m = Math.max(1, Math.round(sec / 60)); return `${m} minute${m === 1 ? '' : 's'}` }
