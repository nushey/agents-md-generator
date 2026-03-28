import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export interface User {
  id: number;
  name: string;
}

export interface IUserService {
  getUser(id: number): Promise<User>;
}

export interface Serializable {
  serialize(): string;
}

@Injectable()
export class UserService implements IUserService, Serializable {
  constructor(private http: HttpClient) {}

  getUser(id: number): Promise<User> {
    return this.http.get<User>(`/api/users/${id}`).toPromise();
  }

  serialize(): string {
    return JSON.stringify(this);
  }

  private validateUser(user: User): boolean {
    return !!user.name;
  }
}

export class BaseRepo {
  connect(): void {}
}

export class SqlRepo extends BaseRepo implements Serializable {
  findAll(): Promise<User[]> {
    return Promise.resolve([]);
  }
}

@Controller('/api/users')
export class UserController {
  @Get(':id')
  findOne(id: string): Promise<User> {
    return Promise.resolve({ id: +id, name: '' });
  }
}

export function formatName(user: User): string {
  return user.name.trim();
}
