import { imageSet, type ImageName } from '@/lib/images'
import { cn } from '@/lib/utils'

export interface PictureProps {
  name: ImageName | string
  /** Describes the picture for people who cannot see it. Use an empty string for decoration. */
  alt: string
  /** Which width the browser should pick at each screen size. */
  sizes: string
  /** True for the main image at the top of a page: loaded at once and at high priority. */
  priority?: boolean
  className?: string
}

/**
 * A responsive WebP image with its real width and height (no layout shift), a `srcset`, and lazy
 * loading unless it is above the fold.
 */
export function Picture({ name, alt, sizes, priority = false, className }: PictureProps) {
  const image = imageSet(name)
  return (
    <img
      src={image.src}
      srcSet={image.srcSet}
      sizes={sizes}
      width={image.width}
      height={image.height}
      alt={alt}
      loading={priority ? 'eager' : 'lazy'}
      decoding={priority ? 'sync' : 'async'}
      {...(priority ? { fetchpriority: 'high' } : {})}
      className={cn('block h-auto w-full object-cover', className)}
    />
  )
}
