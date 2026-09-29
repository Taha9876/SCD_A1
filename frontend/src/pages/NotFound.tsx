import { IconArrowLeft } from '../components/Icon'
import { Link } from '../components/Link'
import { EmptyState } from '../components/ui'

/**
 * Any path that is not one of the four routes. nginx serves index.html for
 * every non-/api path (so deep links work), which means an unknown path lands
 * here rather than on an nginx 404 page.
 */
export function NotFound({ path }: { path: string }) {
  return (
    <section className="panel">
      <EmptyState
        title="There is no page here"
        body={`Nothing lives at ${path}. The complaint may have been linked wrongly, or the address mistyped.`}
        action={
          <Link to="/" className="button button-quiet">
            <IconArrowLeft />
            Report a problem
          </Link>
        }
      />
    </section>
  )
}
