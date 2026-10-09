import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Badge, Skeleton } from '@/components/ui/display'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/disclosure'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import {
  useIntentChange,
  useIntents,
  useKbDocument,
  useKbDocuments,
  useKbSave,
  useKbSearch,
  useReembed,
} from '@/console/api'
import { ApiError } from '@/lib/api-client'
import { FormAlert } from '@/lib/auth-forms'
import { longDay } from '@/pages/portal/format'

const message = (error: unknown) =>
  error instanceof ApiError && error.status < 500
    ? error.message
    : 'That did not work. Please try again.'

function Editor({ slug, onDone }: { slug: string | 'new'; onDone: () => void }) {
  const doc = useKbDocument(slug === 'new' ? null : slug)
  if (slug !== 'new' && doc.isLoading) return <Skeleton className="h-64 w-full" />
  return <EditorForm slug={slug} initial={doc.data} onDone={onDone} />
}

function EditorForm({
  slug,
  initial,
  onDone,
}: {
  slug: string | 'new'
  initial: { slug: string; title: string; category: string; body: string } | undefined
  onDone: () => void
}) {
  const isNew = slug === 'new'
  const save = useKbSave()
  const { toast } = useToast()
  const [form, setForm] = React.useState({
    slug: initial?.slug ?? '',
    title: initial?.title ?? '',
    category: initial?.category ?? 'general',
    body: initial?.body ?? '',
  })
  const [problem, setProblem] = React.useState<string>()
  const [preview, setPreview] = React.useState(false)

  return (
    <form
      noValidate
      aria-label={isNew ? 'New article' : 'Edit article'}
      className="grid gap-4"
      onSubmit={async (event) => {
        event.preventDefault()
        setProblem(undefined)
        try {
          await save.mutateAsync({ ...form, isNew })
          toast({ tone: 'success', title: 'Saved and re-embedded.' })
          onDone()
        } catch (error) {
          setProblem(message(error))
        }
      }}
    >
      <FormAlert message={problem} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          label="Address (slug)"
          required
          hint="Letters, digits and hyphens. Cannot change later."
        >
          {(c) => (
            <Input
              {...c}
              value={form.slug}
              disabled={!isNew}
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
            />
          )}
        </Field>
        <Field label="Title" required>
          {(c) => (
            <Input
              {...c}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          )}
        </Field>
        <Field label="Category" required>
          {(c) => (
            <Input
              {...c}
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            />
          )}
        </Field>
      </div>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant={preview ? 'secondary' : 'primary'}
          onClick={() => setPreview(false)}
        >
          Write
        </Button>
        <Button
          type="button"
          size="sm"
          variant={preview ? 'primary' : 'secondary'}
          onClick={() => setPreview(true)}
        >
          Preview
        </Button>
      </div>
      {preview ? (
        <div className="rounded-xl border bg-card p-4" aria-label="Preview">
          <h3 className="text-xl">{form.title}</h3>
          {form.body.split(/\n{2,}/).map((para, i) => (
            <p key={i} className="mt-3 whitespace-pre-line">
              {para}
            </p>
          ))}
        </div>
      ) : (
        <Field
          label="Article text"
          required
          hint="The assistant answers from this text. Keep each article about one topic."
        >
          {(c) => (
            <Textarea
              {...c}
              rows={14}
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
            />
          )}
        </Field>
      )}
      <div className="flex gap-2">
        <Button
          type="submit"
          loading={save.isPending}
          disabled={!form.slug || !form.title || !form.body}
        >
          Save and re-embed
        </Button>
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function Documents() {
  const docs = useKbDocuments()
  const reembed = useReembed()
  const { toast } = useToast()
  const [editing, setEditing] = React.useState<string | null>(null)
  if (editing) return <Editor slug={editing} onDone={() => setEditing(null)} />
  return (
    <div>
      <div className="flex justify-end">
        <Button onClick={() => setEditing('new')}>New article</Button>
      </div>
      {docs.isLoading ? (
        <Skeleton className="mt-4 h-48 w-full" />
      ) : (
        <ul className="mt-4 grid gap-2">
          {docs.data?.map((d) => (
            <li
              key={d.slug}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-3"
            >
              <div>
                <p className="font-semibold">{d.title}</p>
                <p className="text-sm text-muted-foreground">
                  {d.category}, {d.chunks} passages, updated {longDay(d.updated_at)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {d.stale && <Badge tone="warning">Needs re-embedding</Badge>}
                <Button
                  size="sm"
                  variant="secondary"
                  loading={reembed.isPending && reembed.variables === d.slug}
                  onClick={() =>
                    reembed.mutate(d.slug, {
                      onSuccess: () => toast({ tone: 'success', title: 'Re-embedded.' }),
                    })
                  }
                >
                  Re-embed <span className="sr-only">{d.title}</span>
                </Button>
                <Button size="sm" onClick={() => setEditing(d.slug)}>
                  Edit <span className="sr-only">{d.title}</span>
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Tester() {
  const [q, setQ] = React.useState('')
  const results = useKbSearch(q)
  return (
    <div className="grid gap-4">
      <Field
        label="Try a question"
        hint="Shows the passages the assistant would use, with how close each one is."
      >
        {(c) => <Input {...c} type="search" value={q} onChange={(e) => setQ(e.target.value)} />}
      </Field>
      <ul className="grid gap-2">
        {results.data?.map((r) => (
          <li key={`${r.slug}-${r.chunk_index}`} className="rounded-xl border bg-card p-3 text-sm">
            <p className="flex items-center justify-between gap-2">
              <strong>{r.title}</strong>
              <Badge tone="brand">{Math.round(r.score * 100)}% match</Badge>
            </p>
            <p className="mt-1 text-muted-foreground">{r.text}</p>
          </li>
        ))}
        {q.trim().length > 2 && results.data?.length === 0 && (
          <li className="text-sm text-muted-foreground">No passages matched.</li>
        )}
      </ul>
    </div>
  )
}

function Intents() {
  const intents = useIntents()
  const change = useIntentChange()
  const { toast } = useToast()
  const [form, setForm] = React.useState({ intent: '', text: '' })
  const [problem, setProblem] = React.useState<string>()
  const grouped = new Map<string, { id: string; text: string }[]>()
  for (const i of intents.data ?? []) grouped.set(i.intent, [...(grouped.get(i.intent) ?? []), i])
  return (
    <div className="grid gap-6">
      <p className="text-sm text-muted-foreground">
        Example sentences teach the assistant which question a visitor is asking. Add a few
        different wordings for each intent.
      </p>
      <form
        noValidate
        aria-label="Add an example"
        className="grid gap-3 sm:grid-cols-[200px_1fr_auto] sm:items-end"
        onSubmit={async (event) => {
          event.preventDefault()
          setProblem(undefined)
          try {
            await change.mutateAsync({ add: form })
            toast({ tone: 'success', title: 'Example added.' })
            setForm({ ...form, text: '' })
          } catch (error) {
            setProblem(message(error))
          }
        }}
      >
        <div className="sm:col-span-3">
          <FormAlert message={problem} />
        </div>
        <Field label="Intent" hint="Lowercase, with underscores.">
          {(c) => (
            <Input
              {...c}
              value={form.intent}
              onChange={(e) => setForm({ ...form, intent: e.target.value })}
              list="intent-names"
            />
          )}
        </Field>
        <Field label="Example sentence">
          {(c) => (
            <Input
              {...c}
              value={form.text}
              onChange={(e) => setForm({ ...form, text: e.target.value })}
            />
          )}
        </Field>
        <Button
          type="submit"
          loading={change.isPending}
          disabled={!form.intent || form.text.length < 3}
        >
          Add example
        </Button>
        <datalist id="intent-names">
          {[...grouped.keys()].map((k) => (
            <option key={k} value={k} />
          ))}
        </datalist>
      </form>
      {intents.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        [...grouped.entries()].map(([name, list]) => (
          <section key={name} aria-label={name}>
            <h3 className="text-lg">
              {name} <span className="text-sm text-muted-foreground">({list.length})</span>
            </h3>
            <ul className="mt-2 grid gap-1">
              {list.map((e) => (
                <li
                  key={e.id}
                  className="flex items-center justify-between gap-2 rounded-md border bg-card px-3 py-1.5 text-sm"
                >
                  {e.text}
                  <Button size="sm" variant="ghost" onClick={() => change.mutate({ remove: e.id })}>
                    Remove <span className="sr-only">&ldquo;{e.text}&rdquo;</span>
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}

export function KnowledgePage() {
  return (
    <div>
      <h1 className="text-3xl">Knowledge base</h1>
      <Tabs defaultValue="articles" className="mt-6">
        <TabsList aria-label="Knowledge base">
          <TabsTrigger value="articles">Articles</TabsTrigger>
          <TabsTrigger value="test">Test a question</TabsTrigger>
          <TabsTrigger value="intents">Intent examples</TabsTrigger>
        </TabsList>
        <TabsContent value="articles" className="mt-6">
          <Documents />
        </TabsContent>
        <TabsContent value="test" className="mt-6">
          <Tester />
        </TabsContent>
        <TabsContent value="intents" className="mt-6">
          <Intents />
        </TabsContent>
      </Tabs>
    </div>
  )
}
