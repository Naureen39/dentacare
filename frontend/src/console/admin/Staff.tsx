import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Badge, Skeleton } from '@/components/ui/display'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, controlClasses } from '@/components/ui/input'
import { useToast } from '@/components/ui/toast'
import {
  useChangeRole,
  useCreateStaff,
  useResetMfa,
  useStaffUsers,
  useUpdateStaff,
  type StaffUser,
} from '@/console/api'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth'
import { FormAlert } from '@/lib/auth-forms'
import { cn } from '@/lib/utils'

const message = (error: unknown) =>
  error instanceof ApiError && error.status < 500
    ? error.message
    : 'That did not work. Please try again.'

function CreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateStaff()
  const { toast } = useToast()
  const [form, setForm] = React.useState({
    email: '',
    role: 'receptionist',
    full_name: '',
    specialty: 'General dentistry',
  })
  const [problem, setProblem] = React.useState<string>()
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a member of staff</DialogTitle>
          <DialogDescription>
            They receive an email with a link to choose their own password.
          </DialogDescription>
        </DialogHeader>
        <form
          noValidate
          aria-label="Add a member of staff"
          className="grid gap-4"
          onSubmit={async (event) => {
            event.preventDefault()
            setProblem(undefined)
            try {
              await create.mutateAsync({
                email: form.email,
                role: form.role,
                ...(form.role === 'dentist'
                  ? { full_name: form.full_name, specialty: form.specialty }
                  : {}),
              })
              toast({ tone: 'success', title: 'Account created. An email was sent.' })
              onClose()
            } catch (error) {
              setProblem(message(error))
            }
          }}
        >
          <FormAlert message={problem} />
          <Field label="Email address" required>
            {(c) => (
              <Input
                {...c}
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            )}
          </Field>
          <Field label="Role" required>
            {(c) => (
              <select
                {...c}
                className={cn(controlClasses, 'h-11')}
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                <option value="receptionist">Receptionist</option>
                <option value="dentist">Dentist</option>
                <option value="admin">Administrator</option>
              </select>
            )}
          </Field>
          {form.role === 'dentist' && (
            <>
              <Field
                label="Full name"
                required
                hint="As patients see it, for example Dr. Ada Quill."
              >
                {(c) => (
                  <Input
                    {...c}
                    value={form.full_name}
                    onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  />
                )}
              </Field>
              <Field label="Specialty">
                {(c) => (
                  <Input
                    {...c}
                    value={form.specialty}
                    onChange={(e) => setForm({ ...form, specialty: e.target.value })}
                  />
                )}
              </Field>
            </>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={!form.email}>
              Create account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function StaffPage() {
  const { user } = useAuth()
  const users = useStaffUsers()
  const update = useUpdateStaff()
  const role = useChangeRole()
  const reset = useResetMfa()
  const { toast } = useToast()
  const [creating, setCreating] = React.useState(false)
  const [confirm, setConfirm] = React.useState<StaffUser | null>(null)
  const [problem, setProblem] = React.useState<string>()

  const act = async (task: () => Promise<unknown>, done: string) => {
    setProblem(undefined)
    try {
      await task()
      toast({ tone: 'success', title: done })
    } catch (error) {
      setProblem(message(error))
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Staff</h1>
        <Button onClick={() => setCreating(true)}>Add staff</Button>
      </div>
      <FormAlert message={problem} />
      {users.isLoading ? (
        <Skeleton className="mt-6 h-48 w-full" />
      ) : (
        <div className="mt-6 overflow-x-auto rounded-xl border bg-card">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Staff accounts</caption>
            <thead className="bg-muted text-xs uppercase">
              <tr>
                <th scope="col" className="p-3">
                  Email
                </th>
                <th scope="col" className="p-3">
                  Role
                </th>
                <th scope="col" className="p-3">
                  Status
                </th>
                <th scope="col" className="p-3">
                  Two step
                </th>
                <th scope="col" className="p-3">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {users.data?.map((u) => {
                const self = u.id === user?.id
                return (
                  <tr key={u.id} className="border-t">
                    <th scope="row" className="p-3 font-normal">
                      {u.email}
                      {u.dentist_name && (
                        <span className="block text-xs text-muted-foreground">
                          {u.dentist_name}
                        </span>
                      )}
                    </th>
                    <td className="p-3">
                      <select
                        aria-label={`Role of ${u.email}`}
                        className={cn(controlClasses, 'h-9 w-40')}
                        value={u.role}
                        disabled={self}
                        onChange={(e) =>
                          act(
                            () => role.mutateAsync({ id: u.id, role: e.target.value }),
                            'Role changed.',
                          )
                        }
                      >
                        <option value="receptionist">Receptionist</option>
                        <option value="dentist">Dentist</option>
                        <option value="admin">Administrator</option>
                      </select>
                    </td>
                    <td className="p-3">
                      <Badge tone={u.is_active ? 'success' : 'neutral'}>
                        {u.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </td>
                    <td className="p-3">{u.mfa_enabled ? 'On' : 'Off'}</td>
                    <td className="p-3">
                      <div className="flex flex-wrap justify-end gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={self}
                          onClick={() =>
                            act(
                              () => update.mutateAsync({ id: u.id, is_active: !u.is_active }),
                              u.is_active ? 'Account deactivated.' : 'Account activated.',
                            )
                          }
                        >
                          {u.is_active ? 'Deactivate' : 'Activate'}{' '}
                          <span className="sr-only">{u.email}</span>
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={self || !u.mfa_enabled}
                          onClick={() => setConfirm(u)}
                        >
                          Reset two step <span className="sr-only">for {u.email}</span>
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <CreateDialog open={creating} onClose={() => setCreating(false)} />
      <Dialog open={confirm !== null} onOpenChange={(v) => !v && setConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset two step verification?</DialogTitle>
            <DialogDescription>
              {confirm?.email} will be signed out everywhere and must set up their authenticator app
              again at the next sign in.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setConfirm(null)}>
              Keep it
            </Button>
            <Button
              variant="destructive"
              loading={reset.isPending}
              onClick={() =>
                act(async () => {
                  if (confirm) await reset.mutateAsync(confirm.id)
                  setConfirm(null)
                }, 'Two step verification was reset.')
              }
            >
              Reset
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
