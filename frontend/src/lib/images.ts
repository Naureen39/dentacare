import manifest from '@/assets/images/manifest.json'

type Entry = { aspect: [number, number]; widths: number[] }

const files = import.meta.glob('/src/assets/images/*.webp', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

export type ImageName = keyof typeof manifest

export interface ImageSet {
  src: string
  srcSet: string
  /** The largest width and its height: the browser reserves this shape before the file loads. */
  width: number
  height: number
}

/** The URLs, `srcset` and intrinsic size of an image made by scripts/generate_site_assets.py. */
export function imageSet(name: ImageName | string): ImageSet {
  const entry = (manifest as unknown as Record<string, Entry>)[name]
  if (!entry) throw new Error(`Unknown image: ${name}`)
  const [aw, ah] = entry.aspect
  const urls = entry.widths.map((width) => {
    const url = files[`/src/assets/images/${name}-${width}.webp`]
    if (!url) throw new Error(`Missing image file: ${name}-${width}.webp`)
    return { width, url }
  })
  const largest = urls[urls.length - 1] as { width: number; url: string }
  return {
    src: largest.url,
    srcSet: urls.map((u) => `${u.url} ${u.width}w`).join(', '),
    width: largest.width,
    height: Math.round((largest.width * ah) / aw),
  }
}
