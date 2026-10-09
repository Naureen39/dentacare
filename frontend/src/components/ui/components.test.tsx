import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type * as MotionReact from 'motion/react'
import { useReducedMotion } from 'motion/react'
import { axe } from 'vitest-axe'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { DataTable, compareValues, type Column } from '@/components/ui/data-table'
import { Avatar, Badge, Card, Skeleton, initials } from '@/components/ui/display'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
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
import { Input } from '@/components/ui/input'
import { Rating, RatingInput, StatCard } from '@/components/ui/metrics'
import { AnimatedNumber } from '@/components/ui/motion'
import { Breadcrumbs, EmptyState, Pagination, Stepper, pageItems } from '@/components/ui/navigation'
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
import { codeField, emailField, fieldErrors, phoneField, requiredText } from '@/lib/forms'
import { renderUi } from '@/test/utils'

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof MotionReact>()),
  useReducedMotion: vi.fn(() => false),
}))

// jsdom has no layout or paint, so colour contrast is checked from the tokens in contrast.test.ts.
const axeOptions = { rules: { 'color-contrast': { enabled: false } } }
async function expectAccessible(container: HTMLElement) {
  expect(await axe(container, axeOptions)).toHaveNoViolations()
}

describe('Button', () => {
  it('is busy and inert while loading, keeping its label', async () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        Save
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Save' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('renders a link with button styling when asChild is used', () => {
    render(
      <MemoryRouter>
        <Button asChild>
          <a href="/x">Go</a>
        </Button>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Go' })).toBeInTheDocument()
  })
})

describe('Field', () => {
  it('ties label, hint and error to the control', () => {
    render(
      <Field label="Email" hint="We send a confirmation." error="Enter an email address." required>
        {(c) => <Input {...c} />}
      </Field>,
    )
    const input = screen.getByLabelText(/email/i)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-required', 'true')
    const described = input.getAttribute('aria-describedby') ?? ''
    expect(described.split(' ')).toHaveLength(2)
    expect(screen.getByRole('alert')).toHaveTextContent('Enter an email address.')
    expect(document.getElementById(described.split(' ')[0] as string)).toHaveTextContent(
      'We send a confirmation.',
    )
  })

  it('has no error attributes when valid', async () => {
    const { container } = render(<Field label="Name">{(c) => <Input {...c} />}</Field>)
    const input = screen.getByLabelText('Name')
    expect(input).not.toHaveAttribute('aria-invalid')
    expect(input).not.toHaveAttribute('aria-describedby')
    await expectAccessible(container)
  })
})

describe('form validation helpers', () => {
  it('give specific, polite messages', () => {
    const schema = z.object({
      name: requiredText('your name', 10),
      email: emailField,
      phone: phoneField,
      code: codeField,
    })
    const result = schema.safeParse({ name: '', email: 'nope', phone: '123', code: '12' })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(fieldErrors(result.error)).toEqual({
        name: 'Enter your name.',
        email: 'Enter an email address such as name@example.com.',
        phone: 'Enter a phone number with at least 7 digits.',
        code: 'Enter the 6 digit code.',
      })
    }
    expect(
      schema.safeParse({ name: 'Jo', email: 'jo@example.com', phone: '', code: '123456' }).success,
    ).toBe(true)
    expect(requiredText('a note', 5).safeParse('toolong').error?.issues[0]?.message).toBe(
      'A note must be at most 5 characters.',
    )
  })
})

describe('choices', () => {
  it('Checkbox, Switch and RadioGroup are keyboard operable and labelled', async () => {
    const user = userEvent.setup()
    const { container } = render(
      <div>
        <Checkbox id="c" aria-label="Agree" />
        <Switch id="s" aria-label="Reminders" />
        <RadioGroup aria-label="Contact" defaultValue="a">
          <RadioGroupItem value="a" aria-label="Email" />
          <RadioGroupItem value="b" aria-label="Text" />
        </RadioGroup>
      </div>,
    )
    await user.tab()
    expect(screen.getByRole('checkbox', { name: 'Agree' })).toHaveFocus()
    await user.keyboard(' ')
    expect(screen.getByRole('checkbox', { name: 'Agree' })).toBeChecked()
    await user.tab()
    await user.keyboard(' ')
    expect(screen.getByRole('switch', { name: 'Reminders' })).toBeChecked()
    await user.tab()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('radio', { name: 'Text' })).toHaveFocus()
    await user.keyboard(' ')
    expect(screen.getByRole('radio', { name: 'Text' })).toBeChecked()
    await expectAccessible(container)
  })

  it('Select opens with the keyboard and picks an option', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <Field label="Service">
        {(c) => (
          <Select onValueChange={onChange}>
            <SelectTrigger {...c}>
              <SelectValue placeholder="Choose" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="clean">Cleaning</SelectItem>
              <SelectItem value="crown">Crown</SelectItem>
            </SelectContent>
          </Select>
        )}
      </Field>,
    )
    const trigger = screen.getByRole('combobox', { name: 'Service' })
    trigger.focus()
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('option', { name: 'Crown' }))
    expect(onChange).toHaveBeenCalledWith('crown')
  })
})

describe('disclosure', () => {
  it('Tabs move with arrow keys and show one panel', async () => {
    const user = userEvent.setup()
    const { container } = render(
      <Tabs defaultValue="a">
        <TabsList aria-label="Sections">
          <TabsTrigger value="a">One</TabsTrigger>
          <TabsTrigger value="b">Two</TabsTrigger>
        </TabsList>
        <TabsContent value="a">First panel</TabsContent>
        <TabsContent value="b">Second panel</TabsContent>
      </Tabs>,
    )
    await user.tab()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Two' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Second panel')).toBeVisible()
    expect(screen.queryByText('First panel')).not.toBeInTheDocument()
    await expectAccessible(container)
  })

  it('Accordion expands and collapses with the keyboard', async () => {
    const user = userEvent.setup()
    const { container } = render(
      <Accordion type="single" collapsible>
        <AccordionItem value="q">
          <AccordionTrigger>Question</AccordionTrigger>
          <AccordionContent>Answer</AccordionContent>
        </AccordionItem>
      </Accordion>,
    )
    const trigger = screen.getByRole('button', { name: 'Question' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await user.tab()
    await user.keyboard('{Enter}')
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Answer')).toBeVisible()
    await expectAccessible(container)
  })
})

describe('Dialog', () => {
  it('traps focus, closes on Escape and gives focus back', async () => {
    const user = userEvent.setup()
    render(
      <Dialog>
        <DialogTrigger asChild>
          <Button>Open</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogTitle>Cancel visit</DialogTitle>
          <DialogDescription>This cannot be undone.</DialogDescription>
          <DialogClose asChild>
            <Button>Keep</Button>
          </DialogClose>
        </DialogContent>
      </Dialog>,
    )
    const opener = screen.getByRole('button', { name: 'Open' })
    await user.click(opener)
    const dialog = await screen.findByRole('dialog', { name: 'Cancel visit' })
    expect(dialog).toHaveAccessibleDescription('This cannot be undone.')
    await user.tab()
    await user.tab()
    await user.tab()
    expect(dialog).toContainElement(document.activeElement as HTMLElement) // focus never leaves
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(opener).toHaveFocus()
  })
})

describe('Toast', () => {
  function Demo() {
    const { toast } = useToast()
    return (
      <Button onClick={() => toast({ tone: 'success', title: 'Saved', description: 'All done.' })}>
        Show
      </Button>
    )
  }

  it('announces a message and can be dismissed', async () => {
    const user = userEvent.setup()
    renderUi(<Demo />)
    await user.click(screen.getByRole('button', { name: 'Show' }))
    const toast = await screen.findByText('Saved')
    expect(toast).toBeVisible()
    expect(screen.getByText('All done.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /dismiss notification/i }))
    await waitFor(() => expect(screen.queryByText('Saved')).not.toBeInTheDocument())
  })

  it('refuses to be used outside its provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Demo />)).toThrow(/ToastProvider/)
    spy.mockRestore()
  })
})

describe('display', () => {
  it('Avatar shows initials and a text alternative', async () => {
    expect(initials('Dr. Priya Raman')).toBe('PR')
    expect(initials('Cher')).toBe('C')
    render(<Avatar name="Dr. Priya Raman" />)
    expect(screen.getByRole('img', { name: 'Dr. Priya Raman' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('PR')).toBeInTheDocument())
  })

  it('Skeleton is hidden from assistive technology', () => {
    render(
      <div data-testid="holder">
        <Skeleton className="h-4" />
      </div>,
    )
    expect(screen.getByTestId('holder').firstElementChild).toHaveAttribute('aria-hidden', 'true')
  })

  it('Badge and Card render their content', async () => {
    const { container } = render(
      <Card variant="interactive">
        <Badge tone="success">Confirmed</Badge>
      </Card>,
    )
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    await expectAccessible(container)
  })
})

describe('Calendar', () => {
  it('marks the chosen day and moves by day, week and month with the keyboard', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    const { container } = render(<Calendar value="2026-10-14" onSelect={onSelect} />)
    expect(screen.getByRole('grid', { name: 'October 2026' })).toBeInTheDocument()
    const chosen = screen.getByRole('button', { name: 'Wednesday, October 14, 2026' })
    expect(chosen).toHaveAttribute('aria-pressed', 'true')
    chosen.focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('button', { name: 'Thursday, October 15, 2026' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('button', { name: 'Thursday, October 22, 2026' })).toHaveFocus()
    await user.keyboard('{Home}')
    expect(screen.getByRole('button', { name: 'Sunday, October 18, 2026' })).toHaveFocus()
    await user.keyboard('{PageDown}')
    expect(screen.getByRole('grid', { name: 'November 2026' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Wednesday, November 18, 2026' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith('2026-11-18')
    await expectAccessible(container)
  })

  it('has one tab stop and disables days outside the allowed range', async () => {
    render(
      <Calendar
        value="2026-10-14"
        min="2026-10-10"
        max="2026-10-20"
        onSelect={() => {}}
        isDisabled={(d) => d === '2026-10-15'}
      />,
    )
    const stops = screen
      .getAllByRole('button')
      .filter((b) => b.getAttribute('tabindex') === '0' && b.dataset.date)
    expect(stops).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Friday, October 9, 2026' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Thursday, October 15, 2026' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Wednesday, October 21, 2026' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Friday, October 16, 2026' })).toBeEnabled()
  })

  it('changes month with the buttons', async () => {
    const user = userEvent.setup()
    render(<Calendar value="2026-12-14" onSelect={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'Next month' }))
    expect(screen.getByRole('grid', { name: 'January 2027' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Previous month' }))
    await user.click(screen.getByRole('button', { name: 'Previous month' }))
    expect(screen.getByRole('grid', { name: 'November 2026' })).toBeInTheDocument()
  })
})

describe('DatePicker', () => {
  it('opens a calendar, writes the chosen day on the button and closes', async () => {
    const user = userEvent.setup()
    function Harness() {
      const [value, setValue] = React.useState<string>()
      return (
        <Field label="Date">
          {(c) => <DatePicker {...c} value={value} onChange={setValue} min="2026-10-01" />}
        </Field>
      )
    }
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: /date/i })
    expect(trigger).toHaveTextContent('Choose a date')
    await user.click(trigger)
    await user.click(await screen.findByRole('button', { name: 'Friday, October 16, 2026' }))
    await waitFor(() => expect(screen.queryByRole('grid')).not.toBeInTheDocument())
    expect(trigger).toHaveTextContent('October 16, 2026')
  })
})

describe('SlotPicker', () => {
  const days: SlotDay[] = [
    {
      date: '2026-10-14',
      slots: [
        { id: 'a', label: '9:00 AM' },
        { id: 'b', label: '9:45 AM', detail: 'Dr. Raman' },
        { id: 'c', label: '10:30 AM' },
      ],
    },
    { date: '2026-10-15', slots: [] },
    { date: '2026-10-16', slots: [{ id: 'd', label: '2:00 PM' }] },
  ]

  it('shows the first day with openings and lets a time be chosen', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { container } = render(<SlotPicker days={days} onChange={onChange} />)
    expect(
      screen.getByRole('heading', { name: 'Times on Wednesday, October 14, 2026' }),
    ).toBeInTheDocument()
    const group = screen.getByRole('radiogroup', { name: /available times/i })
    expect(within(group).getAllByRole('radio')).toHaveLength(3)
    expect(screen.getByRole('button', { name: 'Thursday, October 15, 2026' })).toBeDisabled() // no openings
    await user.click(screen.getByRole('radio', { name: /9:45 AM/ }))
    expect(onChange).toHaveBeenCalledWith('b', '2026-10-14')
    await expectAccessible(container)
  })

  it('moves between times with the arrow keys and switches day', async () => {
    const user = userEvent.setup()
    render(<SlotPicker days={days} value="a" onChange={() => {}} />)
    screen.getByRole('radio', { name: '9:00 AM' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('radio', { name: /9:45 AM/ })).toHaveFocus()
    await user.click(screen.getByRole('button', { name: 'Friday, October 16, 2026' }))
    expect(screen.getAllByRole('radio')).toHaveLength(1)
    expect(screen.getByRole('radio', { name: '2:00 PM' })).toBeInTheDocument()
  })

  it('says so when nothing is available', () => {
    render(<SlotPicker days={[{ date: '2026-10-14', slots: [] }]} onChange={() => {}} />)
    expect(screen.getByRole('heading', { name: 'No times available' })).toBeInTheDocument()
  })
})

describe('DataTable', () => {
  interface Row {
    id: string
    name: string
    amount: number
  }
  const rows: Row[] = Array.from({ length: 25 }, (_, i) => ({
    id: String(i),
    name: `Patient ${String.fromCharCode(90 - i)}`,
    amount: (i * 37) % 101,
  }))
  const columns: Column<Row>[] = [
    { key: 'name', header: 'Name', cell: (r) => r.name, sortValue: (r) => r.name },
    {
      key: 'amount',
      header: 'Amount',
      align: 'right',
      cell: (r) => `$${r.amount}`,
      sortValue: (r) => r.amount,
    },
    { key: 'note', header: 'Note', cell: () => '-' },
  ]

  it('names itself, scrolls, and has real headers', async () => {
    const { container } = render(
      <DataTable caption="Visits" columns={columns} rows={rows} getRowId={(r) => r.id} />,
    )
    expect(screen.getByRole('table', { name: 'Visits' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /visits, scrollable/i })).toHaveAttribute(
      'tabindex',
      '0',
    )
    expect(screen.getAllByRole('columnheader')).toHaveLength(3)
    expect(screen.getAllByRole('row')).toHaveLength(11) // header plus ten
    await expectAccessible(container)
  })

  it('sorts ascending, then descending, then back, and announces it', async () => {
    const user = userEvent.setup()
    render(
      <DataTable
        caption="Visits"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        pageSize={5}
      />,
    )
    const header = screen.getByRole('columnheader', { name: /amount/i })
    expect(header).toHaveAttribute('aria-sort', 'none')
    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    const amounts = () =>
      screen
        .getAllByRole('row')
        .slice(1)
        .map((r) => Number(within(r).getAllByRole('cell')[1]?.textContent?.slice(1)))
    expect(amounts()).toEqual([...amounts()].sort((a, b) => a - b))
    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(amounts()).toEqual([...amounts()].sort((a, b) => b - a))
    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'none')
    expect(screen.getByRole('columnheader', { name: 'Note' })).not.toHaveAttribute('aria-sort')
  })

  it('pages through the rows', async () => {
    const user = userEvent.setup()
    render(
      <DataTable
        caption="Visits"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        pageSize={10}
      />,
    )
    expect(screen.getByText('Showing 1 to 10 of 25')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Page 3' }))
    expect(screen.getByText('Showing 21 to 25 of 25')).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(6)
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  })

  it('shows skeleton rows while loading and an empty state with no rows', () => {
    const { rerender } = render(
      <DataTable caption="Visits" columns={columns} rows={[]} getRowId={(r) => r.id} loading />,
    )
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true')
    rerender(
      <DataTable
        caption="Visits"
        columns={columns}
        rows={[]}
        getRowId={(r) => r.id}
        emptyTitle="No visits yet"
      />,
    )
    expect(screen.getByRole('heading', { name: 'No visits yet' })).toBeInTheDocument()
  })

  it('compares numbers numerically and text naturally', () => {
    expect(compareValues(2, 10)).toBeLessThan(0)
    expect(compareValues('Room 2', 'Room 10')).toBeLessThan(0)
    expect(compareValues('apple', 'Banana')).toBeLessThan(0)
  })
})

describe('navigation', () => {
  it('Pagination shows a window of pages', () => {
    expect(pageItems(1, 5)).toEqual([1, 2, 3, 4, 5])
    expect(pageItems(1, 12)).toEqual([1, 2, 'gap', 11, 12])
    expect(pageItems(6, 12)).toEqual([1, 2, 'gap', 5, 6, 7, 'gap', 11, 12])
    expect(pageItems(12, 12)).toEqual([1, 2, 'gap', 11, 12])
  })

  it('Pagination marks the current page and reports changes', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    const { container } = render(<Pagination page={2} pageCount={4} onPageChange={onPageChange} />)
    expect(screen.getByRole('button', { name: 'Page 2' })).toHaveAttribute('aria-current', 'page')
    await user.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onPageChange).toHaveBeenCalledWith(3)
    await expectAccessible(container)
    expect(
      render(<Pagination page={1} pageCount={1} onPageChange={() => {}} />).container,
    ).toBeEmptyDOMElement()
  })

  it('Breadcrumbs mark the current page and link the rest', async () => {
    const { container } = render(
      <MemoryRouter>
        <Breadcrumbs
          items={[
            { label: 'Home', to: '/' },
            { label: 'Services', to: '/services' },
            { label: 'Crowns' },
          ]}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
    expect(screen.getByText('Crowns')).toHaveAttribute('aria-current', 'page')
    await expectAccessible(container)
  })

  it('Stepper announces done, current and upcoming steps', async () => {
    const { container } = render(<Stepper steps={['Service', 'Time', 'Details']} current={1} />)
    const items = screen.getAllByRole('listitem')
    expect(items[1]).toHaveAttribute('aria-current', 'step')
    expect(within(items[0] as HTMLElement).getByText('completed')).toBeInTheDocument()
    expect(within(items[1] as HTMLElement).getByText('current')).toBeInTheDocument()
    await expectAccessible(container)
  })

  it('EmptyState explains and offers an action', async () => {
    const { container } = render(
      <EmptyState
        title="No messages"
        description="New ones appear here."
        action={<Button>Refresh</Button>}
      />,
    )
    expect(screen.getByRole('heading', { name: 'No messages' })).toBeInTheDocument()
    await expectAccessible(container)
  })
})

describe('metrics', () => {
  it('Rating has an exact text alternative', () => {
    render(<Rating value={4.5} />)
    expect(screen.getByRole('img', { name: 'Rated 4.5 out of 5' })).toBeInTheDocument()
  })

  it('RatingInput is a keyboard operable radio group', async () => {
    const user = userEvent.setup()
    function Harness() {
      const [value, setValue] = React.useState(0)
      return <RatingInput value={value} onChange={setValue} />
    }
    const { container } = render(<Harness />)
    await user.tab()
    expect(screen.getByRole('radio', { name: '1 star' })).toHaveFocus()
    await user.keyboard('{ArrowRight}{ArrowRight}')
    expect(screen.getByRole('radio', { name: '3 stars' })).toBeChecked()
    expect(screen.getByRole('radio', { name: '3 stars' })).toHaveFocus()
    await expectAccessible(container)
  })

  it('StatCard says whether a change is good or bad, in words', () => {
    const { rerender } = render(<StatCard label="Collected" value={1200} change={8.4} />)
    expect(screen.getByText('+8.4%')).toBeInTheDocument()
    expect(screen.getByText(/up, which is better/)).toBeInTheDocument()
    rerender(
      <StatCard label="No show rate" value={9} change={-0.6} changeUnit=" points" lowerIsBetter />,
    )
    expect(screen.getByText('-0.6 points')).toBeInTheDocument()
    expect(screen.getByText(/down, which is better/)).toBeInTheDocument()
    rerender(<StatCard label="Utilization" value={70} change={null} />)
    expect(screen.getByText('No earlier figure')).toBeInTheDocument()
    rerender(<StatCard label="Visits" value={5} change={0} />)
    expect(screen.getByText(/no change/)).toBeInTheDocument()
  })

  it('AnimatedNumber exposes the final value to assistive technology at once', async () => {
    render(
      <AnimatedNumber value={412800} format={(v) => `$${Math.round(v).toLocaleString('en-US')}`} />,
    )
    expect(screen.getByText('$412,800', { selector: '.sr-only' })).toBeInTheDocument()
    await act(async () => {})
  })

  it('AnimatedNumber shows the value straight away when motion is reduced', () => {
    vi.mocked(useReducedMotion).mockReturnValue(true)
    render(<AnimatedNumber value={321} />)
    expect(screen.getByText('321', { selector: '[aria-hidden="true"]' })).toBeInTheDocument()
    vi.mocked(useReducedMotion).mockReturnValue(false)
  })
})
