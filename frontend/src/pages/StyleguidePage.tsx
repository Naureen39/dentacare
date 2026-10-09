import { zodResolver } from '@hookform/resolvers/zod'
import { Calendar as CalendarIcon, Inbox } from 'lucide-react'
import * as React from 'react'
import { useForm } from 'react-hook-form'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { z } from 'zod'

import { Chart, chartColors } from '@/components/ui/chart'
import { Button } from '@/components/ui/button'
import {
  Avatar,
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Skeleton,
  Tooltip,
} from '@/components/ui/display'
import { DataTable, type Column } from '@/components/ui/data-table'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DrawerContent,
} from '@/components/ui/dialog'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/disclosure'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { Rating, RatingInput, StatCard } from '@/components/ui/metrics'
import { FadeUp } from '@/components/ui/motion'
import { Breadcrumbs, EmptyState, Pagination, Stepper } from '@/components/ui/navigation'
import { DatePicker, SlotPicker, type SlotDay } from '@/components/ui/pickers'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'
import { Checkbox, RadioGroup, RadioGroupItem, Switch } from '@/components/ui/toggles'
import { addDays, toDateString, type DateString } from '@/lib/dates'
import { contrastRatio } from '@/lib/contrast'
import { emailField, requiredText } from '@/lib/forms'

const swatches = [
  {
    name: 'Navy',
    token: '--primary',
    hex: '#0b2545',
    on: '#ffffff',
    use: 'Headings, primary buttons, footer',
  },
  {
    name: 'Teal (brand)',
    token: '--accent',
    hex: '#13a3a1',
    on: '#0b2545',
    use: 'Icons, fills, large display text',
  },
  {
    name: 'Teal (strong)',
    token: '--accent-strong',
    hex: '#0b7371',
    on: '#ffffff',
    use: 'Links, accent buttons, active states',
  },
  {
    name: 'Mint',
    token: '--secondary',
    hex: '#e8f6f5',
    on: '#0b2545',
    use: 'Tinted surfaces, hover',
  },
  {
    name: 'Warm white',
    token: '--background',
    hex: '#fafbfc',
    on: '#0f172a',
    use: 'Page background',
  },
  {
    name: 'Slate text',
    token: '--muted-foreground',
    hex: '#475569',
    on: '#fafbfc',
    use: 'Secondary text',
  },
  {
    name: 'Success',
    token: '--success-strong',
    hex: '#12704a',
    on: '#e3f5ec',
    use: 'Success text (brand fill #1e9e6a)',
  },
  {
    name: 'Warning',
    token: '--warning-strong',
    hex: '#8a5a00',
    on: '#fdf3dc',
    use: 'Warning text (brand fill #e39b1d)',
  },
  {
    name: 'Danger',
    token: '--destructive',
    hex: '#b42323',
    on: '#fbeaea',
    use: 'Errors, destructive (brand fill #d64545)',
  },
]

const scale = [12, 14, 16, 18, 20, 24, 30, 36, 48, 60]

const days: SlotDay[] = Array.from({ length: 21 }, (_, i) => {
  const date = addDays(toDateString(new Date()), i + 1)
  const weekday = new Date(`${date}T00:00:00`).getDay()
  const times =
    weekday === 0
      ? []
      : weekday === 6
        ? ['9:00 AM', '10:15 AM', '11:30 AM']
        : ['8:30 AM', '9:15 AM', '10:00 AM', '11:00 AM', '1:45 PM', '2:30 PM', '3:15 PM', '4:00 PM']
  return {
    date,
    slots: times.map((label) => ({
      id: `${date}-${label}`,
      label,
      detail: label.startsWith('9') ? 'Dr. Raman' : undefined,
    })),
  }
})

interface Visit {
  id: string
  patient: string
  service: string
  date: string
  amount: number
}
const visits: Visit[] = Array.from({ length: 27 }, (_, i) => ({
  id: String(i + 1),
  patient:
    [
      'Amelia Hartwell',
      'Jordan Lee',
      'Omar Haddad',
      'Sofia Marchetti',
      'Priya Nair',
      'Daniel Reyes',
    ][i % 6] ?? '',
  service: ['Routine Exam and Cleaning', 'Porcelain Crown', 'Tooth Colored Filling'][i % 3] ?? '',
  date: `2026-0${(i % 9) + 1}-${String((i % 27) + 1).padStart(2, '0')}`,
  amount: 120 + ((i * 97) % 900),
}))
const columns: Column<Visit>[] = [
  { key: 'patient', header: 'Patient', cell: (v) => v.patient, sortValue: (v) => v.patient },
  { key: 'service', header: 'Service', cell: (v) => v.service, sortValue: (v) => v.service },
  { key: 'date', header: 'Date', cell: (v) => v.date, sortValue: (v) => v.date },
  {
    key: 'amount',
    header: 'Amount',
    align: 'right',
    cell: (v) => `$${v.amount}`,
    sortValue: (v) => v.amount,
  },
]

const chartData = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'].map((month, i) => ({
  month,
  billed: 82_000 + i * 4_100 + (i % 2) * 3_000,
  collected: 76_000 + i * 3_900 + (i % 2) * 2_000,
}))

const demoForm = z.object({
  name: requiredText('your name', 80),
  email: emailField,
  note: z.string().max(200, 'Keep the note under 200 characters.').optional(),
  agree: z.boolean().refine((value) => value, 'Please accept to continue.'),
})

function Section({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24 border-t py-10">
      <h2 id={`${id}-title`} className="mb-6 text-2xl">
        {title}
      </h2>
      <div className="flex flex-col gap-6">{children}</div>
    </section>
  )
}

function Row({ children, label }: { children: React.ReactNode; label?: string }) {
  return (
    <div
      role={label ? 'group' : undefined}
      aria-label={label}
      className="flex flex-wrap items-center gap-3"
    >
      {children}
    </div>
  )
}

const sections = [
  'Colour',
  'Type',
  'Buttons',
  'Forms',
  'Choices',
  'Overlays',
  'Feedback',
  'Display',
  'Data',
  'Navigation',
  'Dates',
  'Metrics',
]

export default function StyleguidePage() {
  const { toast } = useToast()
  const [date, setDate] = React.useState<DateString>()
  const [slot, setSlot] = React.useState<string>()
  const [rating, setRating] = React.useState(4)
  const [step, setStep] = React.useState(1)
  const [page, setPage] = React.useState(3)
  const [on, setOn] = React.useState(true)
  const form = useForm<z.infer<typeof demoForm>>({
    resolver: zodResolver(demoForm),
    defaultValues: { name: '', email: '', note: '', agree: false },
  })
  const errors = form.formState.errors

  return (
    <div className="container-page py-12">
      <Breadcrumbs items={[{ label: 'Home', to: '/' }, { label: 'Style guide' }]} />
      <h1 className="mt-4 text-4xl">Style guide</h1>
      <p className="mt-3 max-w-2xl text-lg text-muted-foreground">
        Every building block of the Meridian Dental Care interface, with its states. This page is
        only available in development and in builds that turn it on.
      </p>
      <nav aria-label="Style guide sections" className="mt-6 flex flex-wrap gap-2">
        {sections.map((name) => (
          <a
            key={name}
            href={`#${name.toLowerCase()}`}
            className="rounded-full bg-secondary px-3 py-1.5 text-sm font-semibold text-primary hover:bg-accent-strong hover:text-white"
          >
            {name}
          </a>
        ))}
      </nav>

      <Section id="colour" title="Colour">
        <p className="max-w-3xl text-muted-foreground">
          Brand colours are used for fills and large shapes. Wherever a colour carries text, a
          stronger variant that meets WCAG 2.2 AA (4.5 to 1 for text) is used.
        </p>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {swatches.map((s) => (
            <li key={s.token} className="overflow-hidden rounded-xl border bg-card">
              <div
                className="flex h-20 items-end p-3 text-sm font-semibold"
                style={{ background: s.hex, color: s.on }}
              >
                {s.name}
              </div>
              <div className="p-3 text-sm">
                <p className="font-mono text-xs">
                  {s.token} {s.hex}
                </p>
                <p className="text-muted-foreground">{s.use}</p>
                <p className="mt-1 font-semibold">
                  Contrast with its text {contrastRatio(s.hex, s.on).toFixed(1)} : 1
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="type" title="Typography">
        <p className="max-w-3xl text-muted-foreground">
          Headings use Plus Jakarta Sans, body text uses Inter, both served from this site. Body
          text has a line height of 1.5 and large headings 1.15.
        </p>
        <div className="flex flex-col gap-3">
          {scale.map((size) => (
            <p
              key={size}
              className="font-heading font-semibold"
              style={{ fontSize: size, lineHeight: size >= 30 ? 1.15 : 1.5 }}
            >
              {size}px. Modern, comfortable dental care
            </p>
          ))}
        </div>
      </Section>

      <Section id="buttons" title="Buttons">
        <Row label="Variants">
          <Button>Primary</Button>
          <Button variant="accent">Accent</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="link">Link</Button>
        </Row>
        <Row label="Sizes and states">
          <Button size="sm">Small</Button>
          <Button size="lg">Large</Button>
          <Button loading>Saving</Button>
          <Button disabled>Disabled</Button>
          <Button size="icon" aria-label="Open calendar">
            <CalendarIcon className="size-5" aria-hidden="true" />
          </Button>
        </Row>
      </Section>

      <Section id="forms" title="Form controls">
        <form
          noValidate
          className="grid max-w-2xl gap-5"
          onSubmit={form.handleSubmit(() =>
            toast({
              tone: 'success',
              title: 'Form is valid',
              description: 'Nothing was sent: this is a demonstration.',
            }),
          )}
        >
          <Field label="Full name" error={errors.name?.message} required>
            {(c) => <Input {...c} autoComplete="name" {...form.register('name')} />}
          </Field>
          <Field
            label="Email address"
            hint="We only use this to send your confirmation."
            error={errors.email?.message}
            required
          >
            {(c) => <Input {...c} type="email" autoComplete="email" {...form.register('email')} />}
          </Field>
          <Field label="Note" hint="Optional." error={errors.note?.message}>
            {(c) => <Textarea {...c} {...form.register('note')} />}
          </Field>
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
              <Checkbox
                id="agree"
                aria-invalid={errors.agree ? true : undefined}
                aria-describedby={errors.agree ? 'agree-error' : undefined}
                onCheckedChange={(v) =>
                  form.setValue('agree', v === true, { shouldValidate: true })
                }
              />
              <label htmlFor="agree" className="text-sm">
                I accept the privacy policy
              </label>
            </div>
            {errors.agree && (
              <p id="agree-error" role="alert" className="text-sm font-medium text-destructive">
                {errors.agree.message}
              </p>
            )}
          </div>
          <Button type="submit" className="w-fit">
            Check form
          </Button>
        </form>
      </Section>

      <Section id="choices" title="Choices">
        <div className="grid max-w-2xl gap-6 sm:grid-cols-2">
          <Field label="Service">
            {(c) => (
              <Select>
                <SelectTrigger {...c}>
                  <SelectValue placeholder="Choose a service" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="clean">Routine Exam and Cleaning</SelectItem>
                  <SelectItem value="crown">Porcelain Crown</SelectItem>
                  <SelectItem value="fill">Tooth Colored Filling</SelectItem>
                </SelectContent>
              </Select>
            )}
          </Field>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Reminder by</legend>
            <RadioGroup defaultValue="email">
              {['email', 'text message'].map((v) => (
                <div key={v} className="flex items-center gap-3">
                  <RadioGroupItem value={v} id={`r-${v}`} />
                  <label htmlFor={`r-${v}`} className="text-sm capitalize">
                    {v}
                  </label>
                </div>
              ))}
            </RadioGroup>
          </fieldset>
          <div className="flex items-center gap-3">
            <Switch id="remind" checked={on} onCheckedChange={setOn} />
            <label htmlFor="remind" className="text-sm">
              Send appointment reminders ({on ? 'on' : 'off'})
            </label>
          </div>
          <div className="flex items-center gap-3">
            <Checkbox id="news" defaultChecked />
            <label htmlFor="news" className="text-sm">
              Subscribe to the newsletter
            </label>
          </div>
        </div>
      </Section>

      <Section id="overlays" title="Dialog, drawer, tooltip and toast">
        <Row>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="secondary">Open dialog</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Cancel this appointment?</DialogTitle>
                <DialogDescription>
                  You can cancel free of charge until 24 hours before the visit.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="ghost">Keep it</Button>
                </DialogClose>
                <DialogClose asChild>
                  <Button variant="destructive">Cancel appointment</Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="secondary">Open drawer</Button>
            </DialogTrigger>
            <DrawerContent>
              <DialogHeader>
                <DialogTitle>Filters</DialogTitle>
                <DialogDescription>Narrow the list of appointments.</DialogDescription>
              </DialogHeader>
              <Field label="Dentist">{(c) => <Input {...c} placeholder="Any dentist" />}</Field>
            </DrawerContent>
          </Dialog>
          <Tooltip content="Appointments are free to move until the day before.">
            <Button variant="ghost">Hover or focus me</Button>
          </Tooltip>
          <Button
            variant="accent"
            onClick={() =>
              toast({
                tone: 'success',
                title: 'Appointment confirmed',
                description: 'A confirmation is on its way.',
              })
            }
          >
            Success toast
          </Button>
          <Button
            variant="destructive"
            onClick={() =>
              toast({ tone: 'error', title: 'Could not save', description: 'Please try again.' })
            }
          >
            Error toast
          </Button>
        </Row>
      </Section>

      <Section id="feedback" title="Loading and empty states">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card className="p-5" role="status" aria-busy="true" aria-label="Loading example">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="mt-3 h-4 w-full" />
            <Skeleton className="mt-2 h-4 w-4/5" />
          </Card>
          <EmptyState
            icon={<Inbox className="size-6" aria-hidden="true" />}
            title="No appointments yet"
            description="When you book a visit it appears here."
            action={<Button size="sm">Book a visit</Button>}
          />
        </div>
      </Section>

      <Section id="display" title="Cards, badges, avatars and accordion">
        <FadeUp>
          <div className="grid gap-4 md:grid-cols-3">
            <Card variant="interactive">
              <CardHeader>
                <CardTitle>Interactive card</CardTitle>
                <CardDescription>Lifts on hover.</CardDescription>
              </CardHeader>
              <CardContent className="text-sm">Used for services and team members.</CardContent>
              <CardFooter>
                <Badge tone="brand">Preventive</Badge>
              </CardFooter>
            </Card>
            <Card variant="elevated">
              <CardHeader>
                <CardTitle>Elevated card</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">A stronger shadow for featured content.</CardContent>
            </Card>
            <Card variant="tinted">
              <CardHeader>
                <CardTitle>Tinted card</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">A mint surface for callouts.</CardContent>
            </Card>
          </div>
        </FadeUp>
        <Row label="Badges">
          <Badge>Neutral</Badge>
          <Badge tone="brand">Brand</Badge>
          <Badge tone="success">Confirmed</Badge>
          <Badge tone="warning">Pending</Badge>
          <Badge tone="danger">Cancelled</Badge>
          <Badge tone="solid">New</Badge>
        </Row>
        <Row label="Avatars">
          <Avatar name="Dr. Priya Raman" size="sm" />
          <Avatar name="Marcus Lindqvist" />
          <Avatar name="Hannah Okafor" size="lg" />
        </Row>
        <Accordion type="single" collapsible className="max-w-2xl">
          <AccordionItem value="a">
            <AccordionTrigger>How do I cancel an appointment?</AccordionTrigger>
            <AccordionContent>
              Use the link in your reminder email or sign in to your account. Cancelling at least 24
              hours ahead is free.
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="b">
            <AccordionTrigger>Do you accept insurance?</AccordionTrigger>
            <AccordionContent>
              We work with most major plans. Bring your card to your first visit.
            </AccordionContent>
          </AccordionItem>
        </Accordion>
        <Tabs defaultValue="one" className="max-w-2xl">
          <TabsList aria-label="Example tabs">
            <TabsTrigger value="one">Overview</TabsTrigger>
            <TabsTrigger value="two">Billing</TabsTrigger>
            <TabsTrigger value="three">History</TabsTrigger>
          </TabsList>
          <TabsContent value="one">Overview content.</TabsContent>
          <TabsContent value="two">Billing content.</TabsContent>
          <TabsContent value="three">History content.</TabsContent>
        </Tabs>
      </Section>

      <Section id="data" title="Table and chart">
        <DataTable
          caption="Recent visits"
          columns={columns}
          rows={visits}
          getRowId={(v) => v.id}
          pageSize={8}
          maxHeight={360}
        />
        <Chart
          title="Billed and collected revenue"
          description="First half of the year, in US dollars"
          table={{
            columns: ['Month', 'Billed', 'Collected'],
            rows: chartData.map((d) => [d.month, d.billed, d.collected]),
          }}
        >
          <LineChart data={chartData} margin={{ left: 8, right: 8, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="month" tick={{ fill: '#475569', fontSize: 12 }} />
            <YAxis
              tick={{ fill: '#475569', fontSize: 12 }}
              tickFormatter={(v: number) => `$${v / 1000}k`}
            />
            <ChartTooltip />
            <Legend />
            <Line
              type="monotone"
              dataKey="billed"
              name="Billed"
              stroke={chartColors[0]}
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="collected"
              name="Collected"
              stroke={chartColors[1]}
              strokeWidth={2}
              strokeDasharray="6 3"
              dot={false}
            />
          </LineChart>
        </Chart>
      </Section>

      <Section id="navigation" title="Stepper, pagination and breadcrumbs">
        <Stepper steps={['Service', 'Time', 'Details', 'Confirm']} current={step} />
        <Row>
          <Button size="sm" variant="secondary" onClick={() => setStep((s) => Math.max(0, s - 1))}>
            Back
          </Button>
          <Button size="sm" onClick={() => setStep((s) => Math.min(4, s + 1))}>
            Next step
          </Button>
        </Row>
        <Pagination page={page} pageCount={12} onPageChange={setPage} />
      </Section>

      <Section id="dates" title="Date and time pickers">
        <div className="max-w-sm">
          <Field label="Preferred date">
            {(c) => (
              <DatePicker {...c} value={date} onChange={setDate} min={toDateString(new Date())} />
            )}
          </Field>
        </div>
        <SlotPicker days={days} value={slot} onChange={(id) => setSlot(id)} />
        <p className="text-sm text-muted-foreground" role="status">
          {slot ? `Selected: ${slot}` : 'No time selected yet.'}
        </p>
      </Section>

      <Section id="metrics" title="Statistics and ratings">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Collected revenue"
            value={412_800}
            format={(v) => `$${Math.round(v).toLocaleString('en-US')}`}
            change={8.4}
            sparkline={[3, 4, 4, 5, 6, 6, 8]}
          />
          <StatCard
            label="No show rate"
            value={9.3}
            format={(v) => `${v.toFixed(1)}%`}
            change={-0.6}
            changeUnit=" points"
            lowerIsBetter
            sparkline={[10, 9, 11, 9, 10, 9, 9]}
          />
          <StatCard
            label="Utilization"
            value={71}
            format={(v) => `${Math.round(v)}%`}
            change={null}
          />
          <StatCard
            label="New patients"
            value={112}
            change={0}
            hint="Compared with the previous 30 days"
          />
        </div>
        <Row>
          <Rating value={4.6} />
          <span className="text-sm text-muted-foreground">4.6 from 212 reviews</span>
        </Row>
        <Row>
          <RatingInput value={rating} onChange={setRating} />
          <span className="text-sm text-muted-foreground" role="status">
            {rating} of 5 selected
          </span>
        </Row>
      </Section>
    </div>
  )
}
