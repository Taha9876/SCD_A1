/**
 * Client-side validation that MIRRORS the server rules without replacing them.
 *
 * The limits below are the same numbers as the Pydantic model and the database
 * CHECK constraint. That duplication is deliberate and bounded: it exists so a
 * citizen gets instant feedback instead of a round trip, and the server still
 * rejects anything that gets past it. What we never duplicate here is anything
 * the server DECIDES -- category, priority, valid transitions.
 */

export const TEXT_MIN = 10
export const TEXT_MAX = 2000
export const LOCATION_MIN = 3
export const LOCATION_MAX = 200

export interface DraftComplaint {
  text: string
  location: string
  reporter_contact: string
}

export type ValidationErrors = Partial<Record<keyof DraftComplaint, string>>

export function validateDraft(draft: DraftComplaint): ValidationErrors {
  const errors: ValidationErrors = {}
  const text = draft.text.trim()
  const location = draft.location.trim()

  if (text.length === 0) {
    errors.text = 'Please describe the problem.'
  } else if (text.length < TEXT_MIN) {
    errors.text = `Please add a little more detail (at least ${TEXT_MIN} characters).`
  } else if (text.length > TEXT_MAX) {
    errors.text = `Please shorten this to ${TEXT_MAX} characters or fewer.`
  }

  if (location.length === 0) {
    errors.location = 'Please give a location.'
  } else if (location.length < LOCATION_MIN) {
    errors.location = `Location needs at least ${LOCATION_MIN} characters.`
  } else if (location.length > LOCATION_MAX) {
    errors.location = `Location must be ${LOCATION_MAX} characters or fewer.`
  }

  if (draft.reporter_contact.trim().length > 200) {
    errors.reporter_contact = 'Contact must be 200 characters or fewer.'
  }

  return errors
}

export function hasErrors(errors: ValidationErrors): boolean {
  return Object.keys(errors).length > 0
}
