export function getConnectionName(connection: { institution_name: string; display_name?: string | null }): string {
  return connection.display_name ?? connection.institution_name
}
