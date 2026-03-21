import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export interface User {
  id: number;
  name: string;
}

@Injectable()
export class UserService {
  constructor(private http: HttpClient) {}

  getUser(id: number): Promise<User> {
    return this.http.get<User>(`/api/users/${id}`).toPromise();
  }

  private validateUser(user: User): boolean {
    return !!user.name;
  }
}

export function formatName(user: User): string {
  return user.name.trim();
}
