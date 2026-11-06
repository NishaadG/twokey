#!/usr/bin/env bash
# Who answered each key, from Switch's own record. One line per approval:
# command, answered by, state, room. For TWOKEY_APPROVALS_CMD on the board.
exec docker exec "${SWITCH_POSTGRES:-switch-postgres-1}" psql -U postgres -d switch -At -F "$(printf '\t')" -c "
  select replace(a.detail, chr(10), ' '), coalesce(a.answered_by, ''), a.state, r.name
  from approval_requests a join rooms r on r.id = a.room_id
  where a.detail like '%twokey%' and a.state = 'answered'
  order by a.answered_at desc"
