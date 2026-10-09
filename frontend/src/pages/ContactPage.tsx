import { zodResolver } from '@hookform/resolvers/zod'
import { Mail, MapPin, Phone, Siren } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { LocationSection } from '@/components/site/LocationSection'
import { PageHeader, Section } from '@/components/site/parts'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/display'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { clinic, fullAddress } from '@/content/site'
import { ApiError } from '@/lib/api-client'
import { phoneField, requiredText } from '@/lib/forms'
import { useContactMutation } from '@/lib/public-api'
import { localBusinessSchema } from '@/lib/schema'

const schema = z
  .object({
    name: requiredText('your name', 200),
    email: z
      .string()
      .trim()
      .email('Enter an email address such as name@example.com.')
      .or(z.literal('')),
    phone: phoneField,
    message: z
      .string()
      .trim()
      .min(5, 'Please write at least a few words.')
      .max(2000, 'Please keep the message under 2,000 characters.'),
  })
  .refine((v) => v.email !== '' || v.phone !== '', {
    path: ['email'],
    message: 'Give an email address or a phone number so we can reply.',
  })

type Values = z.infer<typeof schema>

export default function ContactPage() {
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', email: '', phone: '', message: '' },
  })
  const mutation = useContactMutation()
  const { errors } = form.formState
  const failure =
    mutation.error instanceof ApiError && mutation.error.status === 429
      ? 'You have sent several messages. Please wait a little, or call us.'
      : mutation.isError
        ? `We could not send your message just now. Please try again or call ${clinic.phone}.`
        : undefined

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Contact' }]}
        title="Contact us"
        intro="Ask a question, request a callback, or tell us how we can help. We reply within one working day."
        seo={{
          description:
            'Contact Meridian Dental Care: phone, emergency line, address, opening hours and a message form.',
          path: '/contact',
          jsonLd: [localBusinessSchema()],
        }}
      />
      <Section>
        <div className="grid gap-10 lg:grid-cols-[1fr_380px]">
          <Card variant="elevated" className="p-6 md:p-8">
            <h2 className="text-2xl">Send a message</h2>
            {mutation.isSuccess ? (
              <div
                role="status"
                className="mt-4 rounded-lg bg-success-soft p-4 text-success-strong"
              >
                <p className="font-semibold">Thank you. Your message has been sent.</p>
                <p className="text-sm">
                  {mutation.data?.message ?? 'We will reply as soon as possible.'}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-3"
                  onClick={() => {
                    mutation.reset()
                    form.reset()
                  }}
                >
                  Send another message
                </Button>
              </div>
            ) : (
              <form
                noValidate
                className="mt-6 grid gap-5"
                onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
              >
                <Field label="Your name" required error={errors.name?.message}>
                  {(c) => <Input {...c} autoComplete="name" {...form.register('name')} />}
                </Field>
                <div className="grid gap-5 sm:grid-cols-2">
                  <Field label="Email address" error={errors.email?.message}>
                    {(c) => (
                      <Input {...c} type="email" autoComplete="email" {...form.register('email')} />
                    )}
                  </Field>
                  <Field
                    label="Phone"
                    hint="Optional if you gave an email."
                    error={errors.phone?.message}
                  >
                    {(c) => (
                      <Input {...c} type="tel" autoComplete="tel" {...form.register('phone')} />
                    )}
                  </Field>
                </div>
                <Field label="How can we help?" required error={errors.message?.message}>
                  {(c) => <Textarea {...c} rows={6} {...form.register('message')} />}
                </Field>
                <p className="text-sm text-muted-foreground">
                  Please do not include medical details. For anything urgent call us instead.
                </p>
                {failure && (
                  <p
                    role="alert"
                    className="rounded-md bg-destructive-soft p-3 text-sm font-medium text-destructive"
                  >
                    {failure}
                  </p>
                )}
                <Button type="submit" size="lg" loading={mutation.isPending} className="w-fit">
                  Send message
                </Button>
              </form>
            )}
          </Card>
          <aside aria-label="Ways to reach us" className="space-y-4">
            <Card className="p-6">
              <h2 className="flex items-center gap-2 text-lg">
                <Phone className="size-5 text-accent-strong" aria-hidden="true" />
                Phone
              </h2>
              <p className="mt-2">
                <a href={clinic.phoneHref} className="text-lg font-semibold">
                  {clinic.phone}
                </a>
              </p>
            </Card>
            <Card className="p-6">
              <h2 className="flex items-center gap-2 text-lg">
                <Siren className="size-5 text-accent-strong" aria-hidden="true" />
                Emergency line
              </h2>
              <p className="mt-2">
                <a href={clinic.emergencyHref} className="text-lg font-semibold">
                  {clinic.emergencyPhone}
                </a>
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                For trouble breathing, spreading swelling or bleeding that will not stop, call 911.
              </p>
            </Card>
            <Card className="p-6">
              <h2 className="flex items-center gap-2 text-lg">
                <Mail className="size-5 text-accent-strong" aria-hidden="true" />
                Email
              </h2>
              <p className="mt-2">
                <a href={`mailto:${clinic.email}`}>{clinic.email}</a>
              </p>
            </Card>
            <Card className="p-6">
              <h2 className="flex items-center gap-2 text-lg">
                <MapPin className="size-5 text-accent-strong" aria-hidden="true" />
                Address
              </h2>
              <p className="mt-2">{fullAddress}</p>
            </Card>
          </aside>
        </div>
      </Section>
      <LocationSection heading="Find us" />
    </>
  )
}
